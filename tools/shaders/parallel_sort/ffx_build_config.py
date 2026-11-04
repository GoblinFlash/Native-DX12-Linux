"""Explicit private FFX input binding. No acquisition, fallback or shell commands."""
import argparse
import hashlib
import json
from pathlib import Path

KEYS = ('base', 'shaders', 'upstream', 'ordinary_spv', 'extra', 'dxc', 'spirv', 'cc', 'cxx', 'spirv_dis')
def need(ok, why):
    if not ok: raise ValueError(why)
def configure():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--config-sha256',required=True)
    parser.add_argument('--output-root',required=True,type=Path)
    a=parser.parse_args()
    raw=a.config.read_bytes()
    need(hashlib.sha256(raw).hexdigest()==a.config_sha256,'CONFIG_SHA')
    c=json.loads(raw)
    need(set(c)=={'schema','roots','paths','pins','compile_flags','libraries'},'CONFIG_SHAPE')
    need(c['schema']=='private-ffx-build.v1' and set(c['paths'])==set(KEYS),'CONFIG_SCHEMA')
    recipe_raw=Path(__file__).with_name('ffx_recipe.json').read_bytes()
    need(hashlib.sha256(recipe_raw).hexdigest()=='08e150c38c0eff4071798715efc21a07a2dd7d6f68ccde449fc04a7d2d1cf904','RECIPE_SHA')
    recipe=json.loads(recipe_raw)
    need(c['compile_flags']==recipe['compile_flags'],'RECIPE_FLAGS')
    need(c['libraries']==recipe['libraries'],'RECIPE_LIBRARIES')
    roots={}
    for k,v in c['roots'].items():
        q=Path(v);need(q.is_absolute() and q.is_dir(),'ROOT:'+k);roots[k]=q.resolve()
    def locate(spec):
        need(isinstance(spec,dict) and set(spec)=={'root','path'},'LOCATOR')
        root=roots[spec['root']];rel=Path(spec['path'])
        need(not rel.is_absolute() and '..' not in rel.parts,'PATH_ESCAPE')
        q=(root/rel).resolve(strict=True)
        need(q.is_relative_to(root),'SYMLINK_ESCAPE')
        return q
    pins={}
    for row in c['pins']:
        need(set(row)=={'root','path','bytes','sha256'},'PIN_SHAPE')
        q=locate({k:row[k] for k in ('root','path')})
        need(q not in pins and q.is_file(),'PIN_FILE')
        b=q.read_bytes();need(len(b)==row['bytes'] and hashlib.sha256(b).hexdigest()==row['sha256'],'INPUT_SHA:'+str(q))
        pins[q]=row
    paths={k:locate(v) for k,v in c['paths'].items()}
    for k in ['dxc','spirv','cc','cxx','spirv_dis','ordinary_spv']:
        need(paths[k] in pins,'UNPINNED:'+k)
    for directory in ['base','shaders','upstream','extra']:
        need(paths[directory].is_dir(),'INPUT_DIR:'+directory)
    for name in ['nvidia_batch_compile.c','nvidia_shared_lowering.h','nir_shared_range.h','shader.bin','shader.info.bin','shader.qmd','shader.nak.txt','shader.json']:
        need(paths['base']/name in pins,'BASE_INPUT_REQUIRED:'+name)
    for directory in ['shaders','upstream','extra']:
        for q in paths[directory].rglob('*'):
            if q.is_file():need(q.resolve() in pins,'UNPINNED_SOURCE:'+str(q))
    for name in ['ParallelSortCount.hlsl','ParallelSortCountReduce.hlsl','ParallelSortScan.hlsl','ParallelSortScanAdd.hlsl','ParallelSortScatter.hlsl','FFX-ParallelSort/FFX_ParallelSort.h']:
        need(paths['shaders']/name in pins,'SHADER_INPUT_REQUIRED:'+name)
    need(paths['upstream']/'ffx-parallelsort/FFX_ParallelSort.h' in pins,'UPSTREAM_HEADER_REQUIRED')
    need(paths['extra']/'ffx_uniform_cf.h' in pins,'EXTRA_HEADER_REQUIRED')
    libraries=[locate(v) for v in c['libraries']]
    need(bool(libraries) and all(x in pins and x.suffix=='.a' for x in libraries),'LIBRARIES')
    flags=[]
    for flag in c['compile_flags']:
        need(isinstance(flag,str) and flag not in ['-c','-o'],'COMPILE_FLAG')
        flags.append(flag.format_map({k:str(v) for k,v in roots.items()}))
    out=a.output_root
    need(out.is_absolute() and not out.exists() and not out.is_symlink(),'OUTPUT_EXISTS')
    # Outputs must not be ancestors or descendants of any declared input root.
    out=out.resolve()
    need(all(not out.is_relative_to(v) and not v.is_relative_to(out) for v in roots.values()),'OUTPUT_OVERLAP')
    need(out.parent.is_dir(),'OUTPUT_PARENT')
    paths.update(area=out.parent,build=out/'build',evidence=out/'evidence',patch_root=out/'patches',flags=flags,libraries=libraries,
                 verified_files=list(pins),config=a.config.resolve(),config_sha256=a.config_sha256)
    return paths
