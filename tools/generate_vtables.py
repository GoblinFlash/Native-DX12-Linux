#!/usr/bin/env python3
"""Generate vtables from explicit package and externally provisioned SDK roots.
Output is create-only. Caller supplies the pinned DirectX-Headers checkout.
"""
import argparse
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package-root', required=True, type=Path)
    parser.add_argument('--directx-headers', required=True, type=Path,
                        help='DirectX-Headers include directory')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.package_root.resolve(strict=True)
    headers = args.directx_headers.resolve(strict=True)
    for required in (root / 'include/ndx12.h', headers / 'directx/d3d12.h',
                     headers / 'wsl/winadapter.h'):
        if not required.is_file():
            raise ValueError('GENERATOR_INPUT_MISSING:' + str(required))
    # Reserve the requested output before preprocessing. Failures retain it;
    # never overwrite source files or silently fall back to m0/m1 paths.
    with args.output.open('x', encoding='utf-8') as destination:
        text = subprocess.check_output(
            ["/usr/bin/g++", "-E", "-P", "-x", "c++", "-std=c++17",
             "-I" + str(headers), "-I" + str(headers / "wsl/stubs"),
             "-I" + str(root / "include"), "-"],
            input='#include "ndx12.h"\n', text=True)
        names = ("ID3D12Device", "ID3D12Resource", "ID3D12CommandAllocator",
                 "ID3D12GraphicsCommandList", "ID3D12CommandQueue", "ID3D12Fence",
                 "ID3D12RootSignature", "ID3D12DescriptorHeap", "ID3D12PipelineState")
        output = []
        for name in names:
            body = re.search(r"typedef struct " + name + r"Vtbl\s*\{(.*?)\}\s*" + name + r"Vtbl;", text, re.S).group(1)
            methods = re.findall(r"\(\s*\*\s*(\w+)\s*\)\s*\(", body)
            if methods[:3] != ["QueryInterface", "AddRef", "Release"]:
                raise ValueError("VTABLE_IUNKNOWN:" + name)
            output.append(f"template<> {name}Vtbl defaults<{name}Vtbl>() {{\n    {name}Vtbl t{{}};")
            for method in methods:
                output.append(f"    t.{method} = unsupported<decltype(t.{method})>::call;")
            output.append("    return t;\n}\n")
        destination.write("\n".join(output))
        print("Generated complete default vtables for", len(names), "pinned SDK interfaces")
        for name in ("ID3D12Resource", "ID3D12DescriptorHeap", "ID3D12CommandQueue"):
            body = re.search(r"typedef struct " + name + r"Vtbl\s*\{(.*?)\}\s*" + name + r"Vtbl;", text, re.S).group(1)
            for method in body.split(";"):
                if "GetDesc" in method or "GetCPUDescriptor" in method or "GetGPUDescriptor" in method:
                    print(name, method.strip())


if __name__ == '__main__':
    main()
