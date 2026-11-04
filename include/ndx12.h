#ifndef NDX12_EXPERIMENTAL_H
#define NDX12_EXPERIMENTAL_H
#ifndef CINTERFACE
#define CINTERFACE
#endif
#ifndef COBJMACROS
#define COBJMACROS
#endif
#include <wsl/winadapter.h>
#include <directx/d3d12.h>

struct Ndx12Stats {
    UINT abi_version;
    UINT vendor_id;
    UINT device_id;
    UINT context_reset_status;
    UINT64 live_buffers;
    UINT64 copies;
    UINT64 dispatches;
    UINT64 submissions;
    UINT64 shader_compiles;
};
struct Ndx12GraphicsStats {
    UINT abi_version;
    UINT64 live_render_targets;
    UINT64 draws;
    UINT64 clears;
    UINT64 texture_copies;
};
struct Ndx12DmaBuf {
    int fd;
    UINT width, height, stride, offset, fourcc;
    UINT64 modifier;
};
struct Ndx12PresentStats {
    UINT abi_version;
    UINT64 created, destroyed, exports, acquired, released, cpu_maps;
};
#ifdef __cplusplus
extern "C" {
#endif
HRESULT Ndx12CreateExperimentalDevice(const char *render_node, REFIID iid, void **device);
HRESULT Ndx12GetStats(ID3D12Device *device, struct Ndx12Stats *stats);
HRESULT Ndx12GetGraphicsStats(ID3D12Device *device, struct Ndx12GraphicsStats *stats);
HRESULT Ndx12CreatePresentResource(ID3D12Device *device, UINT width, UINT height, ID3D12Resource **resource);
HRESULT Ndx12ExportPresentResource(ID3D12Resource *resource, struct Ndx12DmaBuf *buffer);
HRESULT Ndx12AcquireForPresent(ID3D12Resource *resource);
HRESULT Ndx12ReleaseFromPresent(ID3D12Resource *resource);
HRESULT Ndx12GetPresentStats(ID3D12Device *device, struct Ndx12PresentStats *stats);
UINT64 Ndx12LiveObjects(void);
#ifdef __cplusplus
}
#endif
#endif
