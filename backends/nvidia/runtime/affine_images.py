"""Original sealed affine CPU images. No live object, upload or GPU authority."""
from dataclasses import dataclass
import struct
import affine_data as D
import shader_info_check as S
import qmd_bits as Q
import push_bits as B
import gp_entry as G

PUSH_BYTES = 232
WINDOWS = ((0xfe000000,0x1000000),(0xff000000,0x1000000))
GRID = ('CTA_RASTER_WIDTH','CTA_RASTER_HEIGHT','CTA_RASTER_DEPTH')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def span(base, size, alignment=4):
    require(type(base) is int and type(size) is int and 0 < base < 1<<40
            and base % alignment == 0 and 0 < size <= (1<<40)-base,
            'AFFINE_SPAN')
    require(all(base+size<=a or a+n<=base for a,n in WINDOWS), 'AFFINE_WINDOW_ALIAS')


@dataclass(frozen=True)
class Placement:
    role: str
    gpu_base: int
    allocation_size: int
    logical_size: int
    payload_offset: int = 256


def placements(layout, rows):
    require(type(layout) is D.AffineLayout, 'AFFINE_LAYOUT_TYPE');layout.validate()
    require(type(rows) is tuple and len(rows)==4 and all(type(p) is Placement for p in rows)
            and tuple(p.role for p in rows)==D.ROLES, 'AFFINE_PLACEMENTS')
    spans=[]
    for p in rows:
        require(type(p.allocation_size) is int and layout.logical_bytes<=p.allocation_size<=65536
                and p.allocation_size%4096==0 and type(p.logical_size) is int
                and p.logical_size==layout.logical_bytes and type(p.payload_offset) is int
                and p.payload_offset==256, 'AFFINE_PLACEMENT_SIZE')
        span(p.gpu_base,p.allocation_size,4096)
        require(all(p.gpu_base+p.allocation_size<=b or b+n<=p.gpu_base for b,n in spans),
                'AFFINE_DATA_ALIAS');spans.append((p.gpu_base,p.allocation_size))
    return rows


def cb_image(layout, rows):
    rows=placements(layout,rows);raw=bytearray(128);length=4*len(layout.values)
    for i,p in enumerate(rows[:2]):
        require(length<=p.logical_size-p.payload_offset-256, 'AFFINE_VIEW_GUARD')
        struct.pack_into('<QI',raw,16*i,p.gpu_base+p.payload_offset,length)
    struct.pack_into('<8I',raw,48,*layout.params)
    return bytes(raw)


def program():
    S.inspect_affine()
    inv=S.parse(S.pinned((S.HERE.parent / 'data' / 'affine_programs.json'),S.AFFINE_INVENTORY_SHA))
    raw={k:S.pinned(e['path'],e['sha256'],e['size'],e['mode']) for k,e in inv['artifacts'].items()}
    info=S.compare_affine(raw['bin'],raw['info.bin'],S.parse(raw['json']))
    q=raw['qmd'];wanted=dict(QMD_MAJOR_VERSION=3,QMD_VERSION=0,REGISTER_COUNT_V=info['num_gprs'],
        BARRIER_COUNT=0,SHARED_MEMORY_SIZE=0,MIN_SM_CONFIG_SHARED_MEM_SIZE=1,
        MAX_SM_CONFIG_SHARED_MEM_SIZE=26,TARGET_SM_CONFIG_SHARED_MEM_SIZE=1,
        PROGRAM_ADDRESS_LOWER=0,PROGRAM_ADDRESS_UPPER=2,
        PROGRAM_PREFETCH_ADDR_LOWER_SHIFTED=0,PROGRAM_PREFETCH_ADDR_UPPER_SHIFTED=0,
        PROGRAM_PREFETCH_SIZE=0,PROGRAM_PREFETCH_TYPE=0,SASS_VERSION=0,
        SHADER_LOCAL_MEMORY_LOW_SIZE=0,SHADER_LOCAL_MEMORY_HIGH_SIZE=0)
    wanted.update(dict(zip(GRID,(1,1,1))))
    wanted.update({'CTA_THREAD_DIMENSION'+str(i):v for i,v in enumerate((128,1,1))})
    for slot in range(8):
        values=dict(VALID=1,ADDR_LOWER=0x2000,ADDR_UPPER=2,SIZE_SHIFTED4=8,
                    PREFETCH_POST=0,INVALIDATE=0) if slot==0 else dict(
                    VALID=0,ADDR_LOWER=0,ADDR_UPPER=0,SIZE_SHIFTED4=0,PREFETCH_POST=0,INVALIDATE=0)
        wanted.update({'CONSTANT_BUFFER_'+k+'['+str(slot)+']':v for k,v in values.items()})
    require(all(Q.read(q,k)==v for k,v in wanted.items()), 'AFFINE_QMD_SEED')
    return raw['bin'],q


def qmd_image(layout, code_address, cb_address):
    require(type(layout) is D.AffineLayout,'AFFINE_LAYOUT_TYPE');layout.validate()
    code,raw=program();span(code_address,len(code),256);span(cb_address,128,256)
    require(code_address+len(code)<=cb_address or cb_address+128<=code_address,
            'AFFINE_CODE_CB_ALIAS')
    values=dict(zip(GRID,layout.grid))
    values.update(PROGRAM_ADDRESS_LOWER=code_address&0xffffffff,
                  PROGRAM_ADDRESS_UPPER=code_address>>32)
    values.update({'CONSTANT_BUFFER_ADDR_LOWER[0]':cb_address&0xffffffff,
                   'CONSTANT_BUFFER_ADDR_UPPER[0]':cb_address>>32})
    result=raw;mask=0
    for name,value in values.items():
        lo,width=Q.interval(name);mask|=((1<<width)-1)<<lo;result=Q.write(result,name,value)
    require((int.from_bytes(result,'little')^int.from_bytes(raw,'little'))&~mask==0,
            'AFFINE_QMD_IMMUTABLE')
    return result


def push_image(qmd_address, completion, signal):
    span(qmd_address,256,256);span(completion,256,256)
    require(qmd_address+256<=completion or completion+256<=qmd_address,'AFFINE_QMD_COMPLETION_ALIAS')
    require(type(signal) is int and 0<signal<1<<32,'AFFINE_SIGNAL')
    table=B.declarations()
    def val(name):
        r=table[name];require(r['kind']=='value','AFFINE_DECLARATION');return r['value']
    def fld(name,value):
        r=table[name];require(r['kind']=='field' and type(value) is int and 0<=value<1<<r['width'], 'AFFINE_FIELD');return value<<r['lo']
    def packet(name,value):
        sc=1 if name.startswith('NVC9C0_') else 0
        require(name.startswith(('NVC9C0_','NVC56F_')),'AFFINE_METHOD_CLASS')
        address=val(name);require(address%4==0 and 0<=address<=0x3ffc,'AFFINE_METHOD')
        header=fld('NVC56F_DMA_INCR_ADDRESS',address//4)|fld('NVC56F_DMA_INCR_COUNT',1)|fld('NVC56F_DMA_INCR_SUBCHANNEL',sc)|fld('NVC56F_DMA_INCR_OPCODE',val('NVC56F_DMA_INCR_OPCODE_VALUE'))
        return struct.pack('<II',header,value)
    rows=[]
    def put(name,value):rows.append(packet(name,value))
    def membar(op):
        for name,value in [('A',0),('B',0),('C',fld('NVC56F_MEM_OP_C_MEMBAR_TYPE',val('NVC56F_MEM_OP_C_MEMBAR_TYPE_SYS_MEMBAR'))),('D',fld('NVC56F_MEM_OP_D_OPERATION',val(op)))]:put('NVC56F_MEM_OP_'+name,value)
    def invalidate(flags):
        word=0
        for flag in flags:
            name='NVC9C0_INVALIDATE_SHADER_CACHES_'+flag;word|=fld(name,val(name+'_TRUE'))
        put('NVC9C0_INVALIDATE_SHADER_CACHES',word)
    put('NVC9C0_SET_OBJECT',fld('NVC9C0_SET_OBJECT_CLASS_ID',val('ADA_COMPUTE_A')))
    for kind,(base,_) in zip(('SHARED','LOCAL'),WINDOWS):
        n='NVC9C0_SET_SHADER_'+kind+'_MEMORY_WINDOW_'
        put(n+'A',fld(n+'A_BASE_ADDRESS_UPPER',base>>32));put(n+'B',fld(n+'B_BASE_ADDRESS',base&0xffffffff))
    put('NVC9C0_WAIT_FOR_IDLE',0);membar('NVC56F_MEM_OP_D_OPERATION_MEMBAR')
    membar('NVC56F_MEM_OP_D_OPERATION_L2_SYSMEM_INVALIDATE');invalidate(('INSTRUCTION','DATA','CONSTANT'));put('NVC9C0_INVALIDATE_SKED_CACHES',0)
    put('NVC9C0_SEND_PCAS_A',fld('NVC9C0_SEND_PCAS_A_QMD_ADDRESS_SHIFTED8',qmd_address>>8))
    put('NVC9C0_SEND_SIGNALING_PCAS2_B',fld('NVC9C0_SEND_SIGNALING_PCAS2_B_PCAS_ACTION',val('NVC9C0_SEND_SIGNALING_PCAS2_B_PCAS_ACTION_INVALIDATE_COPY_SCHEDULE')))
    put('NVC9C0_WAIT_FOR_IDLE',0);invalidate(('DATA','CONSTANT','FLUSH_DATA'));membar('NVC56F_MEM_OP_D_OPERATION_MEMBAR')
    sem=0
    for field,value in [('OPERATION','RELEASE'),('RELEASE_WFI','EN'),('PAYLOAD_SIZE','32BIT'),('RELEASE_TIMESTAMP','DIS')]:
        name='NVC56F_SEM_EXECUTE_'+field;sem|=fld(name,val(name+'_'+value))
    put('NVC56F_SEM_ADDR_LO',fld('NVC56F_SEM_ADDR_LO_OFFSET',(completion&0xffffffff)>>2));put('NVC56F_SEM_ADDR_HI',fld('NVC56F_SEM_ADDR_HI_OFFSET',completion>>32))
    put('NVC56F_SEM_PAYLOAD_LO',signal);put('NVC56F_SEM_PAYLOAD_HI',0);put('NVC56F_SEM_EXECUTE',sem)
    result=b''.join(rows);require(len(result)==PUSH_BYTES,'AFFINE_PUSH_SIZE');return result


@dataclass(frozen=True)
class ControlSpec:
    gpu_base:int
    allocation_size:int
    ring_offset:int
    userd_offset:int


@dataclass(frozen=True)
class Slot:
    label:str
    offset:int
    used:int
    reserved:int
    gpu_address:int


def control_plan(spec):
    require(type(spec) is ControlSpec and all(type(v) is int for v in vars(spec).values()),'AFFINE_CONTROL_TYPE')
    span(spec.gpu_base,spec.allocation_size,4096)
    require(spec.allocation_size%4096==0 and spec.allocation_size<=64*1024*1024,
            'AFFINE_CONTROL_SIZE')
    r,u=spec.ring_offset,spec.userd_offset
    require(0<=r<=spec.allocation_size-64 and (spec.gpu_base+r)%8==0
            and 0<=u<=spec.allocation_size-512 and u%512==0
            and (r+64<=u or u+512<=r),'AFFINE_CONTROL_FIXED')
    code,_=program();slots=[Slot('ring',r,64,64,spec.gpu_base+r),Slot('userd',u,512,512,spec.gpu_base+u)]
    cursor=0
    for label,used in [('code:affine-u32',len(code)),('cb:0',128),('qmd:0',256),('push',PUSH_BYTES),('completion',4)]:
        reserved=(used+255)//256*256;cursor=(cursor+255)//256*256
        for _ in range(3):
            hit=next(((s.offset,s.offset+s.reserved) for s in slots if cursor<s.offset+s.reserved and s.offset<cursor+reserved),None)
            if hit is None:break
            cursor=(hit[1]+255)//256*256
        require(cursor+reserved<=spec.allocation_size and all(cursor+reserved<=s.offset or s.offset+s.reserved<=cursor for s in slots),'AFFINE_CONTROL_FIT')
        slots.append(Slot(label,cursor,used,reserved,spec.gpu_base+cursor));cursor+=reserved
    return tuple(slots)


@dataclass(frozen=True)
class Images:
    slots:tuple
    cb:bytes
    qmd:bytes
    push:bytes
    control:bytes
    initial_data:tuple


def compose(layout, rows, spec, signal, initial_userd):
    rows=placements(layout,rows);slots=control_plan(spec);by={s.label:s for s in slots}
    require(all(spec.gpu_base+spec.allocation_size<=p.gpu_base or p.gpu_base+p.allocation_size<=spec.gpu_base for p in rows),'AFFINE_CONTROL_DATA_ALIAS')
    require(type(initial_userd) is bytes and len(initial_userd)==512,'AFFINE_USERD_TYPE')
    c=G.A.Abi().struct('Nvc56fControl')
    require(c.size==512 and c.fields['GPGet']==(0x88,4,'u32') and c.fields['GPPut']==(0x8c,4,'u32')
            and struct.unpack_from('<II',initial_userd,0x88)==(0,0),'AFFINE_USERD_INITIAL')
    code,_=program();cb=cb_image(layout,rows);qmd=qmd_image(layout,by['code:affine-u32'].gpu_address,by['cb:0'].gpu_address)
    push=push_image(by['qmd:0'].gpu_address,by['completion'].gpu_address,signal)
    raw=bytearray(b'\xa7'*spec.allocation_size)
    payload={'ring':G.image(by['push'].gpu_address,len(push))+bytes(56),'userd':initial_userd,
             'code:affine-u32':code,'cb:0':cb,'qmd:0':qmd,'push':push,'completion':bytes(4)}
    for slot in slots:
        image=payload[slot.label];require(len(image)==slot.used,'AFFINE_CONTROL_USED')
        raw[slot.offset:slot.offset+slot.used]=image
        if slot.label!='completion':raw[slot.offset+slot.used:slot.offset+slot.reserved]=bytes(slot.reserved-slot.used)
    sizes=tuple(p.allocation_size for p in rows)
    return Images(slots,cb,qmd,push,bytes(raw),layout.initial_images(sizes))


@dataclass(frozen=True)
class ModelResult:
    prefix:int
    signal:int
    grid:tuple
    roles:tuple
    data_sha256:tuple
    control_sha256:str
    control_compared_bytes:int
    status:str = 'CPU_AFFINE_POST_EXECUTION_IMAGE_MODEL_VERIFIED'
    native_execution_proven:bool = False
    flight_retirement_authorized:bool = False


def verify_observed(layout,rows,spec,prefix,signal,initial_userd,control,data,get,put):
    require(type(prefix) is int and prefix==1,'AFFINE_PREFIX')
    require(type(get) is int and type(put) is int and get==put==1,'AFFINE_RING')
    images=compose(layout,rows,spec,signal,initial_userd)
    require(type(control) is bytes and len(control)==spec.allocation_size,'AFFINE_CONTROL_BYTES_TYPE')
    require(type(data) is tuple and len(data)==4 and all(type(x) is bytes for x in data),
            'AFFINE_DATA_BYTES_TYPE')
    by={s.label:s for s in images.slots};u=by['userd'].offset;c=by['completion'].offset
    require(struct.unpack_from('<II',control,u+0x88)==(get,put),'AFFINE_RING_OBSERVATION')
    expected=bytearray(images.control);struct.pack_into('<I',expected,c,signal)
    struct.pack_into('<II',expected,u+0x88,1,1)
    for start,end in ((0,u),(u+0x88,u+0x90),(u+512,len(control))):
        if control[start:end]!=expected[start:end]:
            off=next(i for i in range(start,end) if control[i]!=expected[i])
            slot=next((s for s in images.slots if s.offset<=off<s.offset+s.reserved),None)
            label='hole-or-tail' if slot is None else slot.label
            if label=='qmd:0' and 24<=off-slot.offset<32:label+=':CTA_RASTER_RESUME[192:255]'
            raise ValueError('AFFINE_CONTROL_BYTES:'+label+':offset='+str(off))
    wanted=layout.expected_images(tuple(p.allocation_size for p in rows))
    for role,actual,reference in zip(D.ROLES,data,wanted):
        require(actual==reference,'AFFINE_DATA_BYTES:'+role)
    import hashlib
    return ModelResult(1,signal,layout.grid,D.ROLES,
                       tuple(hashlib.sha256(x).hexdigest() for x in data),
                       hashlib.sha256(control).hexdigest(),len(control)-504)
