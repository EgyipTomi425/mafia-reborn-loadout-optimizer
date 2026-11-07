#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>
#include <stdexcept>
#include <vector>

constexpr int W=12, H=8, CELLS=W*H, MAX_ITEMS=20, MAX_DEPTH=25;
struct Stats {
    double accuracy=0, dodge=0, camouflage=0, crit_damage=0, damage=0,
           resistance=0, rapid=0, crit=0, vs_rogue=0;
    Stats& operator+=(const Stats& b) {
        accuracy+=b.accuracy; dodge+=b.dodge; camouflage+=b.camouflage;
        crit_damage+=b.crit_damage; damage+=b.damage; resistance+=b.resistance;
        rapid+=b.rapid; crit+=b.crit; vs_rogue+=b.vs_rogue;
        return *this;
    }
};
struct Item { std::string id; int w,h,role; Stats stats; };
struct Candidate {
    int id=0, area=0, n=0;
    int items[MAX_ITEMS]{};
    Stats stats;
};
struct Rect { int w,h; };
struct PackInput { int n, holes; Rect rect[MAX_ITEMS]; };
// Three 32-bit words cover all 96 cells, also usable on the host in tests.
struct Board { uint32_t word[3]{}; };
struct Frame {
    Board used;
    uint32_t remaining=0;
    int holes=0, next=0, cell=0;
};
struct PackState {
    Frame stack[MAX_DEPTH];
    int chosen[MAX_DEPTH]{}, position[MAX_DEPTH]{};
    int depth=0, status=0; // 0 pending, 1 packed, 2 proven impossible
    int xy[MAX_ITEMS]{};
    unsigned long long nodes=0;
};
struct Combat {
    double accuracy, dodge, camouflage;
    double landed[2]; // expected damage given hit, against no Vest / Epic Vest
    int vest;
};
struct Ranking {
    int wins=0, ties=0, losses=0;
    double mean_net_pp=0, weighted_win_rate=0, weighted_mean_net_pp=0;
};
struct WeightedRanking { double win_rate=0, mean_net_pp=0; };
struct Scenario { int level=200; double attack=10000, endurance=10000;
    double hp() const { return std::ceil(endurance*(level+1)*3.85); }
};
inline std::vector<Candidate> enumerate(const std::vector<Item>& items) {
    std::vector<Candidate> out;
    int fixed=1;
    while(fixed<static_cast<int>(items.size()) && items[fixed].role==1) ++fixed;
    const int optional=static_cast<int>(items.size())-fixed;
    if(optional<0 || optional>16) throw std::runtime_error("Unsupported optional item count");
    int id=0;
    for(int ammo=0;ammo<fixed;++ammo) for(uint32_t mask=0;mask<(1u<<optional);++mask) {
        Candidate c; c.id=id++;
        auto add=[&](int i){ c.items[c.n++]=i; c.area+=items[i].w*items[i].h;
                            c.stats+=items[i].stats; };
        add(0); if(ammo) add(ammo);
        for(int i=0;i<optional;++i) if(mask&(1u<<i)) add(fixed+i);
        if(c.area>=92 && c.area<=96) out.push_back(c);
    }
    return out;
}
inline PackInput pack_input(const Candidate& c,const std::vector<Item>& items) {
    PackInput p{}; p.n=c.n; p.holes=96-c.area;
    for(int i=0;i<c.n;++i) p.rect[i]={items[c.items[i]].w,items[c.items[i]].h};
    return p;
}
// Antiderivative of floor(x + 0.5), i.e. JS Math.round for positive x.
inline double rounded_integral(double x) {
    double y=x+0.5, n=std::floor(y);
    return n*y-n*(n+1)/2;
}
inline double rapid_mean(double damage) {
    return (rounded_integral(.2*damage)-rounded_integral(.1*damage))/(.1*damage);
}
inline Combat combat(const Candidate& c,const Scenario& scenario) {
    auto s=c.stats;
    double raw=8.5*scenario.level*1.15;
    int low=static_cast<int>(std::floor(raw/2.12));
    int high=static_cast<int>(std::floor(raw+.5))-low;
    double crit=std::clamp((.5+s.crit)*.6,0.0,1.0);
    Combat out{1.17+s.accuracy,std::clamp(.101+s.dodge,0.0,1.0),s.camouflage,
               {0,0},s.resistance>0 ? 1:0};
    for(int vest=0;vest<2;++vest) {
        double sum=0;
        for(int roll=low;roll<=high;++roll) for(int iscrit=0;iscrit<2;++iscrit) {
            double pre=std::floor(.055*std::ceil(scenario.attack)*(1+s.damage)*roll*
                              (iscrit ? 2+s.crit_damage:1)*(1+s.vs_rogue)+.5);
            double d=std::floor(std::max(2.0,pre*(1-.25-(vest?.14:0)))+.5);
            double rapid=d<scenario.hp() ? s.rapid*rapid_mean(d):0;
            sum+=(iscrit?crit:1-crit)*(d+rapid);
        }
        out.landed[vest]=sum/(high-low+1);
    }
    return out;
}
