#include <cuda_runtime.h>
#include "model.hpp"
#include "packing.cuh"
#include "items_generated.hpp"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>

void check(cudaError_t result,const char* call) {
    if(result!=cudaSuccess) throw std::runtime_error(std::string(call)+": "+cudaGetErrorString(result));
}
#define CUDA(call) check((call),#call)
template<class T> struct Device {
    T* ptr=nullptr; size_t n;
    explicit Device(size_t count):n(count) { CUDA(cudaMalloc(&ptr,n*sizeof(T))); }
    ~Device(){ cudaFree(ptr); }
    Device(const Device&)=delete;
    void upload(const std::vector<T>& v) { CUDA(cudaMemcpy(ptr,v.data(),n*sizeof(T),cudaMemcpyHostToDevice)); }
    void download(std::vector<T>& v) { v.resize(n); CUDA(cudaMemcpy(v.data(),ptr,n*sizeof(T),cudaMemcpyDeviceToHost)); }
};
__global__ void initialize(const PackInput* input,PackState* state,int n) {
    int i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i<n) begin_pack(input[i],state[i]);
}
__global__ void pack_kernel(const PackInput* input,PackState* state,int n,unsigned budget) {
    int i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i<n) advance_pack(input[i],state[i],budget);
}
__global__ void statuses(const PackState* state,int* out,int n) {
    int i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i<n) out[i]=state[i].status;
}
HD double damage(const Combat& a,const Combat& b) {
    double hit=a.accuracy-b.camouflage;
    hit=hit<0?0:(hit>1?1:hit);
    return hit*(1-b.dodge)*a.landed[b.vest];
}
HD Ranking rank_one(const Combat* all,int n,int i,double hp) {
    Ranking r{};
    for(int j=0;j<n;++j) if(i!=j) {
        double net=100*(damage(all[i],all[j])-damage(all[j],all[i]))/hp;
        r.mean_net_pp+=net;
        if(net>1e-10) ++r.wins;
        else if(net< -1e-10) ++r.losses;
        else ++r.ties;
    }
    if(n>1) r.mean_net_pp/=n-1;
    return r;
}
__global__ void trade_kernel(const Combat* all,Ranking* out,int n,double hp) {
    int i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i<n) out[i]=rank_one(all,n,i,hp);
}
HD WeightedRanking weighted_rank_one(const Combat* all,const Ranking* base,int n,int i,double hp) {
    WeightedRanking result{};
    double sum_weight=0;
    // weight(j) = base[j].wins / (n-1). The common divisor cancels.
    // Weights are frozen from the UNWEIGHTED all-pairs ranking; no recursion.
    for(int j=0;j<n;++j) if(i!=j) {
        double weight=base[j].wins;
        double net=100*(damage(all[i],all[j])-damage(all[j],all[i]))/hp;
        sum_weight+=weight;
        if(net>1e-10) result.win_rate+=weight;
        result.mean_net_pp+=weight*net;
    }
    if(sum_weight>0) {
        result.win_rate/=sum_weight;
        result.mean_net_pp/=sum_weight;
    } else { // All opponents have zero baseline wins: use uniform weights.
        result.win_rate=static_cast<double>(base[i].wins)/(n-1);
        result.mean_net_pp=base[i].mean_net_pp;
    }
    return result;
}
__global__ void weighted_trade_kernel(const Combat* all,const Ranking* base,WeightedRanking* out,int n,double hp) {
    int i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i<n) out[i]=weighted_rank_one(all,base,n,i,hp);
}

std::vector<PackState> pack_all(const std::vector<PackInput>& inputs,unsigned budget) {
    int n=static_cast<int>(inputs.size());
    if(!n) return {};
    Device<PackInput> d_inputs(n); Device<PackState> d_states(n); Device<int> d_status(n);
    d_inputs.upload(inputs);
    initialize<<<(n+127)/128,128>>>(d_inputs.ptr,d_states.ptr,n); CUDA(cudaGetLastError());
    std::vector<int> status;
    auto start=std::chrono::steady_clock::now();
    int pass=0,pending=n;
    while(pending) {
        pack_kernel<<<(n+127)/128,128>>>(d_inputs.ptr,d_states.ptr,n,budget);
        CUDA(cudaGetLastError());
        statuses<<<(n+127)/128,128>>>(d_states.ptr,d_status.ptr,n); CUDA(cudaGetLastError());
        d_status.download(status);
        pending=static_cast<int>(std::count(status.begin(),status.end(),0));
        double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
        if(++pass==1 || pass%100==0 || !pending)
            std::cout<<"  packing pass="<<pass<<" pending="<<pending
                     <<" valid="<<std::count(status.begin(),status.end(),1)
                     <<" impossible="<<std::count(status.begin(),status.end(),2)
                     <<" elapsed="<<seconds<<"s"<<std::endl;
    }
    std::vector<PackState> result; d_states.download(result);
    for(int i=0;i<n;++i) if(result[i].status==1 && !validate(inputs[i],result[i]))
        throw std::runtime_error("Invalid CUDA placement at candidate "+std::to_string(i));
    return result;
}
std::vector<Ranking> rank_all(const std::vector<Combat>& all,double hp) {
    if(all.size()<2) throw std::runtime_error("Need at least two valid setups");
    int n=static_cast<int>(all.size());
    Device<Combat> d_all(n); Device<Ranking> d_rank(n);
    d_all.upload(all);
    trade_kernel<<<(n+127)/128,128>>>(d_all.ptr,d_rank.ptr,n,hp); CUDA(cudaGetLastError());
    std::vector<Ranking> rank; d_rank.download(rank);
    // Independent execution on host of the full opponent loop for selected rows.
    for(int i:{0,n/2,n-1}) {
        auto reference=rank_one(all.data(),n,i,hp);
        if(reference.wins!=rank[i].wins || reference.ties!=rank[i].ties ||
           reference.losses!=rank[i].losses || std::abs(reference.mean_net_pp-rank[i].mean_net_pp)>1e-9)
            throw std::runtime_error("CPU/CUDA ranking mismatch");
    }
    long long wins=0,losses=0; double sum=0;
    for(auto r:rank) {
        if(r.wins+r.ties+r.losses!=n-1) throw std::runtime_error("Incomplete all-pairs ranking");
        wins+=r.wins; losses+=r.losses; sum+=r.mean_net_pp;
    }
    if(wins!=losses || std::abs(sum)>1e-6) throw std::runtime_error("All-pairs symmetry failed");
    Device<WeightedRanking> d_weighted(n);
    weighted_trade_kernel<<<(n+127)/128,128>>>(d_all.ptr,d_rank.ptr,d_weighted.ptr,n,hp); CUDA(cudaGetLastError());
    std::vector<WeightedRanking> weighted; d_weighted.download(weighted);
    for(int i:{0,n/2,n-1}) {
        auto reference=weighted_rank_one(all.data(),rank.data(),n,i,hp);
        if(std::abs(reference.win_rate-weighted[i].win_rate)>1e-12 ||
           std::abs(reference.mean_net_pp-weighted[i].mean_net_pp)>1e-9)
            throw std::runtime_error("CPU/CUDA weighted ranking mismatch");
    }
    for(int i=0;i<n;++i) {
        rank[i].weighted_win_rate=weighted[i].win_rate;
        rank[i].weighted_mean_net_pp=weighted[i].mean_net_pp;
    }
    return rank;
}
void winner_json(std::ostream& o,const Candidate& c,const PackState& p,const Ranking& r,
                 const std::vector<Item>& items) {
    o<<"{\"candidate_id\":"<<c.id<<",\"area\":"<<c.area<<",\"wins\":"<<r.wins
     <<",\"ties\":"<<r.ties<<",\"losses\":"<<r.losses<<",\"mean_net_hp_pp\":"
     <<r.mean_net_pp<<",\"weighted_win_rate\":"<<r.weighted_win_rate
     <<",\"weighted_mean_net_hp_pp\":"<<r.weighted_mean_net_pp<<",\"items\":[";
    for(int i=0;i<c.n;++i) {
        if(i) o<<',';
        o<<"{\"id\":\""<<items[c.items[i]].id<<"\",\"x\":"<<p.xy[i]%12
         <<",\"y\":"<<p.xy[i]/12<<'}';
    }
    o<<"]}";
}
void run_category(int kind,const Scenario& scenario,const std::filesystem::path& directory,unsigned budget) {
    std::string name=kind==0?"submachine":"rifle";
    auto items=input_items(kind);
    auto candidates=enumerate(items);
    int ammo_choices=1;
    while(ammo_choices<static_cast<int>(items.size()) && items[ammo_choices].role==1) ++ammo_choices;
    const auto optional=items.size()-ammo_choices;
    const auto total=ammo_choices*(1u<<optional);
    std::cout<<name<<": "<<total<<" combinations -> "<<candidates.size()<<" area-qualified"<<std::endl;
    std::vector<PackInput> inputs;
    for(const auto& c:candidates) inputs.push_back(pack_input(c,items));
    auto packed=pack_all(inputs,budget);
    std::ofstream enumeration(directory/(name+"_candidates.csv"));
    enumeration<<"candidate_id,area,status,search_nodes,item_ids\n";
    std::vector<Candidate> valid; std::vector<PackState> layouts;
    for(size_t i=0;i<candidates.size();++i) {
        const auto& c=candidates[i];
        enumeration<<c.id<<','<<c.area<<','<<(packed[i].status==1?"valid":"impossible")<<','<<packed[i].nodes<<',';
        for(int j=0;j<c.n;++j) enumeration<<(j?";":"")<<items[c.items[j]].id;
        enumeration<<'\n';
        if(packed[i].status==1) { valid.push_back(c); layouts.push_back(packed[i]); }
    }
    std::vector<Combat> fighters;
    for(const auto& c:valid) fighters.push_back(combat(c,scenario));
    std::cout<<name<<": CPU retained "<<valid.size()<<" valid setups; comparing "
             <<valid.size()*(valid.size()-1)/2<<" unordered trades"<<std::endl;
    auto ranks=rank_all(fighters,scenario.hp());
    std::ofstream all_layouts(directory/(name+"_valid_setups.jsonl"));
    all_layouts<<std::setprecision(17);
    for(size_t i=0;i<valid.size();++i) {
        winner_json(all_layouts,valid[i],layouts[i],ranks[i],items); all_layouts<<'\n';
    }
    std::vector<int> order(valid.size()); std::iota(order.begin(),order.end(),0);
    auto by_wins=[&](int a,int b) {
        if(ranks[a].wins!=ranks[b].wins) return ranks[a].wins>ranks[b].wins;
        if(ranks[a].mean_net_pp!=ranks[b].mean_net_pp) return ranks[a].mean_net_pp>ranks[b].mean_net_pp;
        return valid[a].id<valid[b].id;
    };
    auto by_mean=[&](int a,int b) {
        if(ranks[a].mean_net_pp!=ranks[b].mean_net_pp) return ranks[a].mean_net_pp>ranks[b].mean_net_pp;
        if(ranks[a].wins!=ranks[b].wins) return ranks[a].wins>ranks[b].wins;
        return valid[a].id<valid[b].id;
    };
    auto by_weighted_wins=[&](int a,int b) {
        if(ranks[a].weighted_win_rate!=ranks[b].weighted_win_rate) return ranks[a].weighted_win_rate>ranks[b].weighted_win_rate;
        if(ranks[a].weighted_mean_net_pp!=ranks[b].weighted_mean_net_pp) return ranks[a].weighted_mean_net_pp>ranks[b].weighted_mean_net_pp;
        return valid[a].id<valid[b].id;
    };
    auto by_weighted_mean=[&](int a,int b) {
        if(ranks[a].weighted_mean_net_pp!=ranks[b].weighted_mean_net_pp) return ranks[a].weighted_mean_net_pp>ranks[b].weighted_mean_net_pp;
        if(ranks[a].weighted_win_rate!=ranks[b].weighted_win_rate) return ranks[a].weighted_win_rate>ranks[b].weighted_win_rate;
        return valid[a].id<valid[b].id;
    };
    std::sort(order.begin(),order.end(),by_wins); int win=order.front();
    std::ofstream csv(directory/(name+"_rankings.csv")); csv<<std::setprecision(17);
    csv<<"rank_by_wins,candidate_id,area,wins,ties,losses,mean_net_hp_pp,weighted_win_rate,weighted_mean_net_hp_pp,item_ids\n";
    for(size_t r=0;r<order.size();++r) {
        int i=order[r]; auto v=ranks[i]; auto c=valid[i];
        csv<<r+1<<','<<c.id<<','<<c.area<<','<<v.wins<<','<<v.ties<<','<<v.losses<<','<<v.mean_net_pp<<','<<v.weighted_win_rate<<','<<v.weighted_mean_net_pp<<',';
        for(int j=0;j<c.n;++j) csv<<(j?";":"")<<items[c.items[j]].id;
        csv<<'\n';
    }
    std::sort(order.begin(),order.end(),by_mean); int mean=order.front();
    std::sort(order.begin(),order.end(),by_weighted_wins); int weighted_win=order.front();
    std::sort(order.begin(),order.end(),by_weighted_mean); int weighted_mean=order.front();
    std::ofstream json(directory/(name+"_results.json")); json<<std::setprecision(17);
    json<<"{\n\"category\":\""<<name<<"\",\"level\":"<<scenario.level
        <<",\"attack\":"<<scenario.attack<<",\"endurance\":"<<scenario.endurance
        <<",\"hp\":"<<scenario.hp()<<",\"all_combinations\":"<<total
        <<",\"optional_items\":"<<optional<<",\"excluded_items\":[\"riot_shield\"]"
        <<",\"ammo_choices_including_none\":"<<ammo_choices
        <<",\"ammo_tier\":\"gold1\",\"ammo_families\":[\"soft_nosed_bullet\",\"tracer_ammunition\"]"
        <<",\"area_qualified\":"<<candidates.size()
        <<",\"valid_setups\":"<<valid.size()<<",\"opponents_per_setup\":"<<valid.size()-1
        <<",\"metric\":\"expected one-exchange net HP percentage points; no full fight\""
        <<",\"weighting\":\"opponent unweighted win rate; exclude self; draws score zero; all-zero weights fall back to uniform\",\n\"most_wins\":";
    winner_json(json,valid[win],layouts[win],ranks[win],items);
    json<<",\n\"best_mean_trade\":";
    winner_json(json,valid[mean],layouts[mean],ranks[mean],items);
    json<<",\n\"best_weighted_win_rate\":";
    winner_json(json,valid[weighted_win],layouts[weighted_win],ranks[weighted_win],items);
    json<<",\n\"best_weighted_mean_trade\":";
    winner_json(json,valid[weighted_mean],layouts[weighted_mean],ranks[weighted_mean],items);
    json<<"\n}\n";
    for(auto i:{win,mean,weighted_win,weighted_mean}) { winner_json(std::cout,valid[i],layouts[i],ranks[i],items); std::cout<<std::endl; }
}
void require(bool condition,const char* message) { if(!condition) throw std::runtime_error(message); }
void self_test() {
    require(enumerate(input_items(0)).size()==7852,"SMG enumeration with two Gold1 ammo families");
    require(enumerate(input_items(1)).size()==9616,"rifle enumeration with two Gold1 ammo families");
    for(int kind=0;kind<2;++kind) {
        auto items=input_items(kind);
        require(items.size()==18,"15 optional items plus weapon and two ammo choices");
        require(items[1].id==(kind==0?"soft_nosed_bullet_small":"soft_nosed_bullet_large"),"Soft-Nosed caliber must match weapon");
        require(items[2].id==(kind==0?"tracer_ammunition_small":"tracer_ammunition_large"),"Tracer caliber must match weapon");
        require(items[1].stats.damage==.11 && items[1].stats.crit_damage==.21,"Gold1 Soft-Nosed bonuses");
        require(items[2].stats.damage==.11 && items[2].stats.accuracy==.11,"Gold1 Tracer bonuses");
        bool rapid_found=false;
        for(const auto& item:items) {
            require(item.id!="riot_shield","Riot Shield must be excluded");
            if(item.id=="rapid_fire") {
                rapid_found=true;
                require(item.w==3 && item.h==3 && item.stats.rapid==.17,"Rapid Fire snapshot stats");
            }
        }
        require(rapid_found,"Rapid Fire must be available");
    }
    std::vector<PackInput> tests;
    PackInput full{}; full.n=8;
    for(int i=0;i<8;++i) full.rect[i]={3,4}; // 96 cells, feasible
    tests.push_back(full);
    PackInput impossible{}; impossible.n=5; impossible.holes=0;
    for(int i=0;i<4;++i) impossible.rect[i]={5,4};
    impossible.rect[4]={4,4}; // 96 cells; cannot split widths 5,5,5,5,4 into 12+12
    tests.push_back(impossible);
    PackInput holes{}; holes.n=8; holes.holes=4;
    for(int i=0;i<7;++i) holes.rect[i]={3,4};
    holes.rect[7]={2,4}; tests.push_back(holes);
    auto results=pack_all(tests,10000);
    require(results[0].status==1 && results[1].status==2 && results[2].status==1,"Packing fixtures");
    for(size_t i=0;i<tests.size();++i) {
        PackState host{}; begin_pack(tests[i],host);
        while(!host.status) advance_pack(tests[i],host,10000);
        require(host.status==results[i].status,"CPU/GPU packing mismatch");
    }
    // Independently known baseline at level 200: uniform rolls 922..1033.
    Candidate c{}; c.stats.crit_damage=.15;
    Scenario scenario;
    auto baseline=combat(c,scenario);
    require(std::abs(baseline.accuracy-1.17)<1e-12,"Epic1 weapon starts at 117% accuracy");
    Stats concealment{};
    Stats camouflage_skill{}; camouflage_skill.camouflage=.22;
    Stats camouflage_suit{}; camouflage_suit.camouflage=.33;
    concealment+=camouflage_skill; concealment+=camouflage_suit;
    require(std::abs(concealment.camouflage-.55)<1e-12,"Camouflage bonuses add to 55 percentage points");
    Combat synthetic_attacker{1.17,0,0,{100,100},0};
    Combat synthetic_defender{1.17,.101,concealment.camouflage,{100,100},0};
    require(std::abs(damage(synthetic_attacker,synthetic_defender)-55.738)<1e-10,
            "117%-55%=62% hit, then multiply by 89.9% non-dodge");
    synthetic_defender.dodge=.201;
    require(std::abs(damage(synthetic_attacker,synthetic_defender)-49.538)<1e-10,
            "Vigilance applies after the accuracy/camouflage check");
    synthetic_attacker.accuracy=1.50; synthetic_defender.camouflage=.40;
    require(std::abs(damage(synthetic_attacker,synthetic_defender)-79.9)<1e-10,
            "Clamp accuracy only after subtracting defender camouflage");
    auto vigilance_candidate=c;
    vigilance_candidate.stats.dodge=.10;
    auto with_vigilance=combat(vigilance_candidate,scenario);
    require(std::abs(baseline.dodge-.101)<1e-12,"No Vigilance: base Rogue dodge only");
    require(std::abs(with_vigilance.dodge-.201)<1e-12,"Vigilance applies only to equipped setup");
    require(std::abs(damage(baseline,with_vigilance)/damage(baseline,baseline)-.799/.899)<1e-12,
            "Each opponent must use its own dodge");
    double expected=0, expected_vest=0;
    for(int roll=922;roll<=1033;++roll) {
        expected+=.7*std::floor(std::floor(550.0*roll+.5)*.75+.5);
        expected+=.3*std::floor(std::floor(550.0*roll*2.15+.5)*.75+.5);
        expected_vest+=.7*std::floor(std::floor(550.0*roll+.5)*.61+.5);
        expected_vest+=.3*std::floor(std::floor(550.0*roll*2.15+.5)*.61+.5);
    }
    require(std::abs(baseline.landed[0]-expected/112)<1e-7,"Rounded damage baseline");
    require(std::abs(baseline.landed[1]-expected_vest/112)<1e-7,
            "Rogue 25% plus Vest 14pp gives 39% reduction, i.e. 61% damage");
    auto vest_candidate=c; vest_candidate.stats.resistance=.14;
    auto with_vest=combat(vest_candidate,scenario);
    require(with_vest.vest==1 && baseline.vest==0,"Vest only affects equipped defender");
    require(std::abs(rapid_mean(100)-15)<1e-9,"Continuous rapid expectation");
    require(std::abs(rapid_mean(101)-15.14851485148515)<1e-8,"Rapid rounding integral");
    auto attack=c; attack.stats.accuracy=.15;
    auto defense=c; defense.stats.resistance=.14; defense.stats.camouflage=.55;
    auto rows=rank_all({baseline,combat(attack,scenario),combat(defense,scenario)},scenario.hp());
    require(rows[0].wins+rows[0].ties+rows[0].losses==2,"Opponent count");
    Combat fixture[3]={{1,0,0,{100,100},0},{1,0,0,{200,200},0},{1,0,0,{50,50},0}};
    Ranking strength[3]{}; strength[1].wins=99; strength[2].wins=1;
    auto weighted=weighted_rank_one(fixture,strength,3,0,100);
    require(std::abs(weighted.win_rate-.01)<1e-12,"Losing to 99-weight opponent and beating 1-weight gives 1% weighted wins");
    require(std::abs(weighted.mean_net_pp+98.5)<1e-12,"Signed trade margin weighted by opponent strength");
    std::cout<<"Self-test passed"<<std::endl;
}
int main(int argc,char** argv) {
    try {
        Scenario scenario; std::string category="both"; std::filesystem::path out="results";
        unsigned budget=20000; bool test=false;
        for(int i=1;i<argc;++i) {
            std::string arg=argv[i];
            auto value=[&](){ if(i+1>=argc) throw std::runtime_error("Missing value for "+arg); return std::string(argv[++i]); };
            if(arg=="--self-test") test=true;
            else if(arg=="--output") out=value();
            else if(arg=="--category") category=value();
            else if(arg=="--level") scenario.level=std::stoi(value());
            else if(arg=="--nodes-per-pass") budget=std::stoul(value());
            else if(arg=="--help") {
                std::cout<<"mafia_cuda [--category both|submachine|rifle] [--level 200] [--output results] [--nodes-per-pass 20000] [--self-test]\n"; return 0;
            } else throw std::runtime_error("Unknown argument: "+arg);
        }
        if(category!="both" && category!="submachine" && category!="rifle") throw std::runtime_error("Invalid category");
        if(scenario.level<1 || budget==0) throw std::runtime_error("Level and node budget must be positive");
        cudaDeviceProp prop{}; CUDA(cudaGetDeviceProperties(&prop,0));
        std::cout<<"GPU: "<<prop.name<<std::endl;
        if(test) { self_test(); return 0; }
        std::filesystem::create_directories(out);
        if(category=="both" || category=="submachine") run_category(0,scenario,out,budget);
        if(category=="both" || category=="rifle") run_category(1,scenario,out,budget);
    } catch(const std::exception& e) { std::cerr<<"ERROR: "<<e.what()<<std::endl; return 1; }
}
