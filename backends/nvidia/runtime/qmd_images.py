"""Original pinned-seed validation/relocation. No memory or publication authority."""
import shader_info_check as S
import qmd_bits as B

GRID = ('CTA_RASTER_WIDTH', 'CTA_RASTER_HEIGHT', 'CTA_RASTER_DEPTH')


def seed(kind):
    S.require(type(kind) is str and kind in S.KINDS, 'QMD_KIND')
    inventory = S.parse(S.pinned((S.HERE.parent / 'data' / 'parallel_sort_programs.json'), S.INVENTORY_SHA))
    entries = inventory['programs'][kind]['artifacts']
    images = {k: S.pinned(e['path'], e['sha256'], e['size'], e['mode']) for k,e in entries.items()}
    meta = S.parse(images['json'])
    info = S.compare(kind, images['bin'], images['info.bin'], meta)
    raw = images['qmd']
    expected = dict(QMD_MAJOR_VERSION=3, QMD_VERSION=0, REGISTER_COUNT_V=info['num_gprs'],
                    BARRIER_COUNT=info['num_control_barriers'],
                    SHARED_MEMORY_SIZE=(info['cs.smem_size']+255)//256*256,
                    MIN_SM_CONFIG_SHARED_MEM_SIZE=3, MAX_SM_CONFIG_SHARED_MEM_SIZE=26,
                    TARGET_SM_CONFIG_SHARED_MEM_SIZE=(26,3,9,9,9)[S.KINDS.index(kind)],
                    PROGRAM_ADDRESS_LOWER=0, PROGRAM_ADDRESS_UPPER=2,
                    PROGRAM_PREFETCH_ADDR_LOWER_SHIFTED=0, PROGRAM_PREFETCH_ADDR_UPPER_SHIFTED=0,
                    PROGRAM_PREFETCH_SIZE=0, PROGRAM_PREFETCH_TYPE=0, SASS_VERSION=0,
                    SHADER_LOCAL_MEMORY_LOW_SIZE=0, SHADER_LOCAL_MEMORY_HIGH_SIZE=0)
    expected.update({name:1 for name in GRID})
    expected.update({'CTA_THREAD_DIMENSION'+str(i):info['cs.local_size['+str(i)+']'] for i in range(3)})
    for slot in range(8):
        values = dict(VALID=1, ADDR_LOWER=0x2000, ADDR_UPPER=2, SIZE_SHIFTED4=8,
                      PREFETCH_POST=0, INVALIDATE=0) if slot == 0 else dict(
                      VALID=0, ADDR_LOWER=0, ADDR_UPPER=0, SIZE_SHIFTED4=0, PREFETCH_POST=0, INVALIDATE=0)
        expected.update({'CONSTANT_BUFFER_'+k+'['+str(slot)+']':v for k,v in values.items()})
    S.require(meta['cb0']['qmd_bytes'] == 128, 'QMD_CB_PROFILE')
    S.require(all(B.read(raw,k)==v for k,v in expected.items()), 'QMD_SEED_RELATION')
    return raw, len(images['bin'])


def _span(address, length):
    S.require(type(address) is int and 0 < address < 1<<49 and address % 256 == 0,
              'QMD_ADDRESS')
    S.require(0 < length <= (1<<49)-address, 'QMD_SPAN')


def image(kind, grid, code_address, cb_address):
    raw, code_length = seed(kind)
    S.require(type(grid) is tuple and len(grid)==3 and all(type(x) is int for x in grid), 'QMD_GRID')
    S.require(all(0 < x < 1<<width for x,width in zip(grid,(32,16,16))), 'QMD_GRID')
    _span(code_address,code_length); _span(cb_address,128)
    S.require(code_address+code_length <= cb_address or cb_address+128 <= code_address, 'QMD_SPAN_ALIAS')
    values = dict(zip(GRID,grid))
    for prefix,address in (('PROGRAM_ADDRESS',code_address),('CONSTANT_BUFFER_ADDR',cb_address)):
        suffix = '[0]' if prefix.startswith('CONSTANT') else ''
        values[prefix+'_LOWER'+suffix] = address & 0xffffffff
        values[prefix+'_UPPER'+suffix] = address >> 32
    for name,value in values.items(): raw = B.write(raw,name,value)
    return raw


def verify(raw, kind, grid, code_address, cb_address):
    S.require(type(raw) is bytes and len(raw)==256, 'QMD_IMAGE_SIZE')
    expected = image(kind,grid,code_address,cb_address)
    original, _ = seed(kind)
    wanted = dict(zip(GRID,grid))
    wanted.update(PROGRAM_ADDRESS_LOWER=code_address & 0xffffffff,
                  PROGRAM_ADDRESS_UPPER=code_address >> 32)
    wanted['CONSTANT_BUFFER_ADDR_LOWER[0]'] = cb_address & 0xffffffff
    wanted['CONSTANT_BUFFER_ADDR_UPPER[0]'] = cb_address >> 32
    mask = 0
    for name, value in wanted.items():
        lo, width = B.interval(name)
        mask |= ((1 << width)-1) << lo
        S.require(B.read(raw,name)==value, 'QMD_RELOCATION_FIELDS')
    changed = int.from_bytes(raw,'little') ^ int.from_bytes(original,'little')
    S.require(changed & ~mask == 0, 'QMD_IMMUTABLE_BITS')
    S.require(raw==expected, 'QMD_IMAGE_MISMATCH')
    return raw
