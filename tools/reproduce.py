"""Rebuild the documented run, verify it independently, and redraw its figure."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def local_directory(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or path == ROOT:
        raise ValueError('Build directory must be inside the repository and distinct from its root')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', default='build')
    parser.add_argument('--host-compiler', help='CUDA-supported C++ compiler, e.g. /usr/bin/g++-11')
    parser.add_argument('--architecture', default='native', help='CMake CUDA architecture; default: native')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    build = local_directory(args.build_dir)
    output = ROOT / 'results'
    output.mkdir(exist_ok=True)
    for name in ('tmp', 'cuda-cache'):
        (build / name).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TMPDIR=str(build/'tmp'), CUDA_CACHE_PATH=str(build/'cuda-cache'),
               OPENBLAS_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
    py = sys.executable
    compiler = args.host_compiler or shutil.which('g++-11')
    configure = ['cmake', '-S', str(ROOT), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
                 f'-DCMAKE_CUDA_ARCHITECTURES={args.architecture}', f'-DPython3_EXECUTABLE={py}']
    if compiler:
        configure += [f'-DCMAKE_CUDA_HOST_COMPILER={compiler}', f'-DCMAKE_CXX_COMPILER={compiler}']
    inputs = sorted([ROOT/'CMakeLists.txt', ROOT/'requirements.txt',
                     *ROOT.glob('src/*'), *ROOT.glob('tools/*.py'), *ROOT.glob('tests/*.py'),
                     *ROOT.glob('data/*.json'), *ROOT.glob('data/client/*.js'),
                     *ROOT.glob('assets/png/*.png')])
    manifest = {
        'status': 'running',
        'input_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs if p.is_file()},
        'python_version': sys.version.split()[0],
        'python_packages': {name: importlib.metadata.version(name) for name in ('numpy', 'scipy', 'Pillow')},
        'scenario': {'level': 200, 'attack': 10000, 'endurance': 10000, 'base_crit': .5, 'anti_crit': .4,
                     'ammo': 'None or one compatible Gold1 Tracer/Soft-Nosed', 'area': [92,96], 'riot_shield': False},
        'steps': [],
    }
    manifest_path = output/'run_manifest.json'
    def persist():
        manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    persist()
    steps = [
        ('theory', [py, 'tests/check_theory.py']),
        ('ammunition', [py, 'tools/verify_ammunition.py']),
        ('rapid_fire', [py, 'tools/verify_rapid_fire.py']),
        ('configure', configure),
        ('build', ['cmake', '--build', str(build), '--parallel', str(args.jobs)]),
        ('self_test', ['ctest', '--test-dir', str(build), '--output-on-failure']),
        ('search', [str(build/'mafia_cuda'), '--output', str(output)]),
        ('audit', [py, 'tests/audit_results.py']),
        ('weighted_recheck', [py, 'tests/recheck_weighted_ranking.py']),
        ('counters', [py, 'tools/analyze_counters.py']),
        ('defensive_core', [py, 'tools/analyze_defensive_core.py']),
        ('findings', [py, 'tools/analyze_findings.py']),
        ('figure', [py, 'tools/render_results.py']),
    ]
    for name, command in steps:
        print(f'[{name}]', flush=True)
        log = output/f'{name}.log'
        with log.open('w') as stream:
            process = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        manifest['steps'].append({'name': name, 'returncode': process.returncode})
        if process.returncode:
            manifest['status'] = 'failed'
            persist()
            print(log.read_text(), file=sys.stderr)
            raise SystemExit(process.returncode)
        persist()
    for kind, count in [('submachine', 2947), ('rifle', 2066)]:
        summary = json.loads((output/f'{kind}_results.json').read_text())
        if summary['valid_setups'] != count:
            raise RuntimeError(f'Unexpected valid setup count for {kind}')
    manifest['status'] = 'complete'
    manifest['figure'] = 'results/loadout_comparison.png'
    manifest['figure_sha256'] = hashlib.sha256((ROOT/manifest['figure']).read_bytes()).hexdigest()
    persist()
    print('Complete: results/loadout_comparison.png; all numerical and packing audits passed.')


if __name__ == '__main__':
    main()
