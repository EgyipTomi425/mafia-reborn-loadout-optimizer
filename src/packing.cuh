#pragma once
#include "model.hpp"
#ifdef __CUDACC__
#define HD __host__ __device__
#else
#define HD
#endif
HD inline bool occupied(const Board& b,int cell) {
    return (b.word[cell/32]>>(cell%32))&1u;
}
HD inline void mark(Board& b,int cell) { b.word[cell/32]|=1u<<(cell%32); }
HD inline int first_empty(const Board& b) {
    for(int i=0;i<3;++i) if(b.word[i]!=0xffffffffu) {
#ifdef __CUDA_ARCH__
        return i*32+__ffs(~b.word[i])-1;
#else
        return i*32+__builtin_ctz(~b.word[i]);
#endif
    }
    return 96;
}
HD inline Board rectangle(int cell,Rect r) {
    Board mask{};
    for(int y=0;y<r.h;++y) {
        int offset=cell+12*y, word=offset/32, shift=offset%32;
        uint32_t row=(1u<<r.w)-1;
        mask.word[word]|=row<<shift;
        if(shift+r.w>32) mask.word[word+1]|=row>>(32-shift);
    }
    return mask;
}
HD inline bool intersects(const Board& a,const Board& b) {
    return (a.word[0]&b.word[0]) || (a.word[1]&b.word[1]) || (a.word[2]&b.word[2]);
}
HD inline void begin_pack(const PackInput& p,PackState& s) {
    s.depth=0; s.status=0; s.nodes=0;
    s.stack[0]=Frame{};
    s.stack[0].remaining=(1u<<p.n)-1;
    s.stack[0].holes=p.holes;
}
// Complete first-empty-cell search. Empty cells are explicit 1x1 holes.
// At the first empty cell any rectangle covering it MUST start there:
// all preceding cells are already occupied (or declared holes).
// Equal-sized remaining items are geometrically interchangeable.
HD inline void advance_pack(const PackInput& p,PackState& s,unsigned budget) {
    if(s.status) return;
    for(unsigned iteration=0;iteration<budget;++iteration) {
        ++s.nodes;
        Frame& f=s.stack[s.depth];
        if(!f.remaining) {
            for(int d=0;d<s.depth;++d) if(s.chosen[d]<p.n)
                s.xy[s.chosen[d]]=s.position[d];
            s.status=1; return;
        }
        if(f.next>p.n || f.cell==96) {
            if(s.depth==0) { s.status=2; return; }
            --s.depth; continue;
        }
        int i=f.next++;
        Board mask{};
        bool hole=i==p.n;
        if(hole) {
            if(!f.holes) continue;
            mark(mask,f.cell);
        } else {
            if(!(f.remaining&(1u<<i))) continue;
            Rect r=p.rect[i];
            bool duplicate=false;
            for(int j=0;j<i;++j) if((f.remaining&(1u<<j)) &&
                p.rect[j].w==r.w && p.rect[j].h==r.h) { duplicate=true; break; }
            if(duplicate || f.cell%12+r.w>12 || f.cell/12+r.h>8) continue;
            mask=rectangle(f.cell,r);
            if(intersects(f.used,mask)) continue;
        }
        Frame child{};
        for(int k=0;k<3;++k) child.used.word[k]=f.used.word[k]|mask.word[k];
        child.remaining=hole?f.remaining:(f.remaining&~(1u<<i));
        child.holes=f.holes-(hole?1:0);
        child.cell=first_empty(child.used);
        s.chosen[s.depth]=i; s.position[s.depth]=f.cell;
        s.stack[++s.depth]=child;
    }
}
inline bool validate(const PackInput& p,const PackState& s) {
    if(s.status!=1) return false;
    Board used{};
    for(int i=0;i<p.n;++i) {
        int cell=s.xy[i]; Rect r=p.rect[i];
        if(cell<0 || cell>=96 || cell%12+r.w>12 || cell/12+r.h>8) return false;
        Board b=rectangle(cell,r);
        if(intersects(used,b)) return false;
        for(int k=0;k<3;++k) used.word[k]|=b.word[k];
    }
    return true;
}
