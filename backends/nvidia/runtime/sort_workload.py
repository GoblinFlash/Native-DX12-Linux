"""Original bounded FFX workload plan, from CONTRACT_B and the workload API.

This is CPU plan validation, not shader execution, packet admission, or proof
of descriptor semantics. See SORT-WORKLOAD-PLAN.md for explicit profile choices.
No old host planner or shader implementation is used as a source.
"""
from dataclasses import dataclass
import struct

from replacement_inputs import arena as A
from sort_data_layout import DataLayout

STAGES = ('count', 'reduce', 'scan', 'scanadd', 'scatter')
ROLES = ('keys0', 'keys1', 'sum', 'reduce')
PARAM_MASKS = (0x4f, 0x14, 0x20, 0x14, 0x4f)


@dataclass(frozen=True)
class View:
    role: str
    words: int
    access: str
    written_words: int


@dataclass(frozen=True)
class Stage:
    index: int
    pass_index: int
    kind: str
    grid: tuple
    params: tuple
    views: tuple


def _canonical(layout):
    A.require(type(layout) is DataLayout, 'WORKLOAD_LAYOUT_TYPE')
    geo, _ = layout.validate()
    n, groups, blocks = geo.keys, geo.groups, geo.blocks
    # Exact scope: U1/U2 and any unreviewed case are refused by layout.validate.
    table_capacity = 16 * blocks
    table_live = 16 * groups
    reduced_live = 16
    result = []
    for pass_index in range(8):
        src = 'keys0' if pass_index % 2 == 0 else 'keys1'
        dst = 'keys1' if pass_index % 2 == 0 else 'keys0'
        key_params = (n, geo.blocks_per_group, groups, 0, 0, 0, 4 * pass_index, 0)
        table_params = (0, 0, groups, 0, 1, 0, 0, 0)
        params = (key_params, table_params, (0, 0, 0, 0, 0, reduced_live, 0, 0),
                  table_params, key_params)
        grids = ((groups, 1, 1), (16, 1, 1), (1, 1, 1), (16, 1, 1), (groups, 1, 1))
        views = (
            (View(src, n, 'R', 0), View('sum', table_capacity, 'W', table_live)),
            (View('sum', table_capacity, 'R', 0), View('reduce', reduced_live, 'W', reduced_live)),
            (View('reduce', reduced_live + 64, 'R', 0), View('reduce', reduced_live + 64, 'W', reduced_live)),
            (View('sum', table_capacity, 'R', 0), View('sum', table_capacity, 'W', table_live),
             View('reduce', reduced_live, 'R', 0)),
            (View(src, n, 'R', 0), View(dst, n + 64, 'W', n), View('sum', table_live, 'R', 0)),
        )
        for local_index, kind in enumerate(STAGES):
            stage = Stage(len(result), pass_index, kind, grids[local_index], params[local_index], views[local_index])
            # View permission does not authorize writes into the diagnostic tail.
            for view in stage.views:
                A.require(layout.payload_offset_words + view.words <= layout.buffer_words - 64,
                          'WORKLOAD_VIEW_GUARD')
            result.append(stage)
    return tuple(result)


def _shape(stage):
    A.require(type(stage) is Stage and type(stage.index) is int and type(stage.pass_index) is int
              and type(stage.kind) is str, 'WORKLOAD_STAGE_TYPE')
    A.require(type(stage.grid) is tuple and len(stage.grid) == 3
              and all(type(x) is int and 0 < x < 2**32 for x in stage.grid), 'WORKLOAD_GRID_TYPE')
    A.require(type(stage.params) is tuple and len(stage.params) == 8
              and all(type(x) is int and 0 <= x < 2**32 for x in stage.params), 'WORKLOAD_PARAMS_TYPE')
    A.require(type(stage.views) is tuple and len(stage.views) in (2, 3), 'WORKLOAD_VIEWS_TYPE')
    for view in stage.views:
        A.require(type(view) is View and type(view.role) is str and view.role in ROLES
                  and type(view.access) is str and view.access in ('R', 'W')
                  and type(view.words) is int and view.words > 0
                  and type(view.written_words) is int and 0 <= view.written_words <= view.words
                  and (view.access != 'R' or view.written_words == 0), 'WORKLOAD_VIEW_TYPE')


@dataclass(frozen=True)
class Workload:
    layout: DataLayout
    stages: tuple

    def validate(self):
        A.require(type(self) is Workload and type(self.stages) is tuple and len(self.stages) == 40,
                  'WORKLOAD_STAGE_SET')
        expected = _canonical(self.layout)
        for actual, wanted in zip(self.stages, expected):
            _shape(actual)
            A.require(actual == wanted, 'WORKLOAD_STAGE_MISMATCH', index=wanted.index)
        return self

    def prefix(self, count):
        self.validate()
        A.require(type(count) is int and 1 <= count <= 40, 'WORKLOAD_PREFIX')
        return self.stages[:count]

    def parameter_images(self):
        self.validate()
        return tuple(struct.pack('<8I', *stage.params) for stage in self.stages)


def plan(layout):
    result = Workload(layout, _canonical(layout))
    return result.validate()
