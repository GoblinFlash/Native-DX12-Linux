template<> ID3D12DeviceVtbl defaults<ID3D12DeviceVtbl>() {
    ID3D12DeviceVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetNodeCount = unsupported<decltype(t.GetNodeCount)>::call;
    t.CreateCommandQueue = unsupported<decltype(t.CreateCommandQueue)>::call;
    t.CreateCommandAllocator = unsupported<decltype(t.CreateCommandAllocator)>::call;
    t.CreateGraphicsPipelineState = unsupported<decltype(t.CreateGraphicsPipelineState)>::call;
    t.CreateComputePipelineState = unsupported<decltype(t.CreateComputePipelineState)>::call;
    t.CreateCommandList = unsupported<decltype(t.CreateCommandList)>::call;
    t.CheckFeatureSupport = unsupported<decltype(t.CheckFeatureSupport)>::call;
    t.CreateDescriptorHeap = unsupported<decltype(t.CreateDescriptorHeap)>::call;
    t.GetDescriptorHandleIncrementSize = unsupported<decltype(t.GetDescriptorHandleIncrementSize)>::call;
    t.CreateRootSignature = unsupported<decltype(t.CreateRootSignature)>::call;
    t.CreateConstantBufferView = unsupported<decltype(t.CreateConstantBufferView)>::call;
    t.CreateShaderResourceView = unsupported<decltype(t.CreateShaderResourceView)>::call;
    t.CreateUnorderedAccessView = unsupported<decltype(t.CreateUnorderedAccessView)>::call;
    t.CreateRenderTargetView = unsupported<decltype(t.CreateRenderTargetView)>::call;
    t.CreateDepthStencilView = unsupported<decltype(t.CreateDepthStencilView)>::call;
    t.CreateSampler = unsupported<decltype(t.CreateSampler)>::call;
    t.CopyDescriptors = unsupported<decltype(t.CopyDescriptors)>::call;
    t.CopyDescriptorsSimple = unsupported<decltype(t.CopyDescriptorsSimple)>::call;
    t.GetResourceAllocationInfo = unsupported<decltype(t.GetResourceAllocationInfo)>::call;
    t.GetCustomHeapProperties = unsupported<decltype(t.GetCustomHeapProperties)>::call;
    t.CreateCommittedResource = unsupported<decltype(t.CreateCommittedResource)>::call;
    t.CreateHeap = unsupported<decltype(t.CreateHeap)>::call;
    t.CreatePlacedResource = unsupported<decltype(t.CreatePlacedResource)>::call;
    t.CreateReservedResource = unsupported<decltype(t.CreateReservedResource)>::call;
    t.CreateSharedHandle = unsupported<decltype(t.CreateSharedHandle)>::call;
    t.OpenSharedHandle = unsupported<decltype(t.OpenSharedHandle)>::call;
    t.OpenSharedHandleByName = unsupported<decltype(t.OpenSharedHandleByName)>::call;
    t.MakeResident = unsupported<decltype(t.MakeResident)>::call;
    t.Evict = unsupported<decltype(t.Evict)>::call;
    t.CreateFence = unsupported<decltype(t.CreateFence)>::call;
    t.GetDeviceRemovedReason = unsupported<decltype(t.GetDeviceRemovedReason)>::call;
    t.GetCopyableFootprints = unsupported<decltype(t.GetCopyableFootprints)>::call;
    t.CreateQueryHeap = unsupported<decltype(t.CreateQueryHeap)>::call;
    t.SetStablePowerState = unsupported<decltype(t.SetStablePowerState)>::call;
    t.CreateCommandSignature = unsupported<decltype(t.CreateCommandSignature)>::call;
    t.GetResourceTiling = unsupported<decltype(t.GetResourceTiling)>::call;
    t.GetAdapterLuid = unsupported<decltype(t.GetAdapterLuid)>::call;
    return t;
}

template<> ID3D12ResourceVtbl defaults<ID3D12ResourceVtbl>() {
    ID3D12ResourceVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetDevice = unsupported<decltype(t.GetDevice)>::call;
    t.Map = unsupported<decltype(t.Map)>::call;
    t.Unmap = unsupported<decltype(t.Unmap)>::call;
    t.GetDesc = unsupported<decltype(t.GetDesc)>::call;
    t.GetGPUVirtualAddress = unsupported<decltype(t.GetGPUVirtualAddress)>::call;
    t.WriteToSubresource = unsupported<decltype(t.WriteToSubresource)>::call;
    t.ReadFromSubresource = unsupported<decltype(t.ReadFromSubresource)>::call;
    t.GetHeapProperties = unsupported<decltype(t.GetHeapProperties)>::call;
    return t;
}

template<> ID3D12CommandAllocatorVtbl defaults<ID3D12CommandAllocatorVtbl>() {
    ID3D12CommandAllocatorVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetDevice = unsupported<decltype(t.GetDevice)>::call;
    t.Reset = unsupported<decltype(t.Reset)>::call;
    return t;
}

template<> ID3D12GraphicsCommandListVtbl defaults<ID3D12GraphicsCommandListVtbl>() {
    ID3D12GraphicsCommandListVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetDevice = unsupported<decltype(t.GetDevice)>::call;
    t.GetType = unsupported<decltype(t.GetType)>::call;
    t.Close = unsupported<decltype(t.Close)>::call;
    t.Reset = unsupported<decltype(t.Reset)>::call;
    t.ClearState = unsupported<decltype(t.ClearState)>::call;
    t.DrawInstanced = unsupported<decltype(t.DrawInstanced)>::call;
    t.DrawIndexedInstanced = unsupported<decltype(t.DrawIndexedInstanced)>::call;
    t.Dispatch = unsupported<decltype(t.Dispatch)>::call;
    t.CopyBufferRegion = unsupported<decltype(t.CopyBufferRegion)>::call;
    t.CopyTextureRegion = unsupported<decltype(t.CopyTextureRegion)>::call;
    t.CopyResource = unsupported<decltype(t.CopyResource)>::call;
    t.CopyTiles = unsupported<decltype(t.CopyTiles)>::call;
    t.ResolveSubresource = unsupported<decltype(t.ResolveSubresource)>::call;
    t.IASetPrimitiveTopology = unsupported<decltype(t.IASetPrimitiveTopology)>::call;
    t.RSSetViewports = unsupported<decltype(t.RSSetViewports)>::call;
    t.RSSetScissorRects = unsupported<decltype(t.RSSetScissorRects)>::call;
    t.OMSetBlendFactor = unsupported<decltype(t.OMSetBlendFactor)>::call;
    t.OMSetStencilRef = unsupported<decltype(t.OMSetStencilRef)>::call;
    t.SetPipelineState = unsupported<decltype(t.SetPipelineState)>::call;
    t.ResourceBarrier = unsupported<decltype(t.ResourceBarrier)>::call;
    t.ExecuteBundle = unsupported<decltype(t.ExecuteBundle)>::call;
    t.SetDescriptorHeaps = unsupported<decltype(t.SetDescriptorHeaps)>::call;
    t.SetComputeRootSignature = unsupported<decltype(t.SetComputeRootSignature)>::call;
    t.SetGraphicsRootSignature = unsupported<decltype(t.SetGraphicsRootSignature)>::call;
    t.SetComputeRootDescriptorTable = unsupported<decltype(t.SetComputeRootDescriptorTable)>::call;
    t.SetGraphicsRootDescriptorTable = unsupported<decltype(t.SetGraphicsRootDescriptorTable)>::call;
    t.SetComputeRoot32BitConstant = unsupported<decltype(t.SetComputeRoot32BitConstant)>::call;
    t.SetGraphicsRoot32BitConstant = unsupported<decltype(t.SetGraphicsRoot32BitConstant)>::call;
    t.SetComputeRoot32BitConstants = unsupported<decltype(t.SetComputeRoot32BitConstants)>::call;
    t.SetGraphicsRoot32BitConstants = unsupported<decltype(t.SetGraphicsRoot32BitConstants)>::call;
    t.SetComputeRootConstantBufferView = unsupported<decltype(t.SetComputeRootConstantBufferView)>::call;
    t.SetGraphicsRootConstantBufferView = unsupported<decltype(t.SetGraphicsRootConstantBufferView)>::call;
    t.SetComputeRootShaderResourceView = unsupported<decltype(t.SetComputeRootShaderResourceView)>::call;
    t.SetGraphicsRootShaderResourceView = unsupported<decltype(t.SetGraphicsRootShaderResourceView)>::call;
    t.SetComputeRootUnorderedAccessView = unsupported<decltype(t.SetComputeRootUnorderedAccessView)>::call;
    t.SetGraphicsRootUnorderedAccessView = unsupported<decltype(t.SetGraphicsRootUnorderedAccessView)>::call;
    t.IASetIndexBuffer = unsupported<decltype(t.IASetIndexBuffer)>::call;
    t.IASetVertexBuffers = unsupported<decltype(t.IASetVertexBuffers)>::call;
    t.SOSetTargets = unsupported<decltype(t.SOSetTargets)>::call;
    t.OMSetRenderTargets = unsupported<decltype(t.OMSetRenderTargets)>::call;
    t.ClearDepthStencilView = unsupported<decltype(t.ClearDepthStencilView)>::call;
    t.ClearRenderTargetView = unsupported<decltype(t.ClearRenderTargetView)>::call;
    t.ClearUnorderedAccessViewUint = unsupported<decltype(t.ClearUnorderedAccessViewUint)>::call;
    t.ClearUnorderedAccessViewFloat = unsupported<decltype(t.ClearUnorderedAccessViewFloat)>::call;
    t.DiscardResource = unsupported<decltype(t.DiscardResource)>::call;
    t.BeginQuery = unsupported<decltype(t.BeginQuery)>::call;
    t.EndQuery = unsupported<decltype(t.EndQuery)>::call;
    t.ResolveQueryData = unsupported<decltype(t.ResolveQueryData)>::call;
    t.SetPredication = unsupported<decltype(t.SetPredication)>::call;
    t.SetMarker = unsupported<decltype(t.SetMarker)>::call;
    t.BeginEvent = unsupported<decltype(t.BeginEvent)>::call;
    t.EndEvent = unsupported<decltype(t.EndEvent)>::call;
    t.ExecuteIndirect = unsupported<decltype(t.ExecuteIndirect)>::call;
    return t;
}

template<> ID3D12CommandQueueVtbl defaults<ID3D12CommandQueueVtbl>() {
    ID3D12CommandQueueVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetDevice = unsupported<decltype(t.GetDevice)>::call;
    t.UpdateTileMappings = unsupported<decltype(t.UpdateTileMappings)>::call;
    t.CopyTileMappings = unsupported<decltype(t.CopyTileMappings)>::call;
    t.ExecuteCommandLists = unsupported<decltype(t.ExecuteCommandLists)>::call;
    t.SetMarker = unsupported<decltype(t.SetMarker)>::call;
    t.BeginEvent = unsupported<decltype(t.BeginEvent)>::call;
    t.EndEvent = unsupported<decltype(t.EndEvent)>::call;
    t.Signal = unsupported<decltype(t.Signal)>::call;
    t.Wait = unsupported<decltype(t.Wait)>::call;
    t.GetTimestampFrequency = unsupported<decltype(t.GetTimestampFrequency)>::call;
    t.GetClockCalibration = unsupported<decltype(t.GetClockCalibration)>::call;
    t.GetDesc = unsupported<decltype(t.GetDesc)>::call;
    return t;
}

template<> ID3D12FenceVtbl defaults<ID3D12FenceVtbl>() {
    ID3D12FenceVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetDevice = unsupported<decltype(t.GetDevice)>::call;
    t.GetCompletedValue = unsupported<decltype(t.GetCompletedValue)>::call;
    t.SetEventOnCompletion = unsupported<decltype(t.SetEventOnCompletion)>::call;
    t.Signal = unsupported<decltype(t.Signal)>::call;
    return t;
}

template<> ID3D12RootSignatureVtbl defaults<ID3D12RootSignatureVtbl>() {
    ID3D12RootSignatureVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetDevice = unsupported<decltype(t.GetDevice)>::call;
    return t;
}

template<> ID3D12DescriptorHeapVtbl defaults<ID3D12DescriptorHeapVtbl>() {
    ID3D12DescriptorHeapVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetDevice = unsupported<decltype(t.GetDevice)>::call;
    t.GetDesc = unsupported<decltype(t.GetDesc)>::call;
    t.GetCPUDescriptorHandleForHeapStart = unsupported<decltype(t.GetCPUDescriptorHandleForHeapStart)>::call;
    t.GetGPUDescriptorHandleForHeapStart = unsupported<decltype(t.GetGPUDescriptorHandleForHeapStart)>::call;
    return t;
}

template<> ID3D12PipelineStateVtbl defaults<ID3D12PipelineStateVtbl>() {
    ID3D12PipelineStateVtbl t{};
    t.QueryInterface = unsupported<decltype(t.QueryInterface)>::call;
    t.AddRef = unsupported<decltype(t.AddRef)>::call;
    t.Release = unsupported<decltype(t.Release)>::call;
    t.GetPrivateData = unsupported<decltype(t.GetPrivateData)>::call;
    t.SetPrivateData = unsupported<decltype(t.SetPrivateData)>::call;
    t.SetPrivateDataInterface = unsupported<decltype(t.SetPrivateDataInterface)>::call;
    t.SetName = unsupported<decltype(t.SetName)>::call;
    t.GetDevice = unsupported<decltype(t.GetDevice)>::call;
    t.GetCachedBlob = unsupported<decltype(t.GetCachedBlob)>::call;
    return t;
}
