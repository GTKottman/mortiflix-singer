"""Runs DiffSinger's scripts/export.py with one fix: newer onnxsim tags every simplified graph with its own
metadata (removed node counts), and onnx.compose.merge_models refuses to merge graphs whose metadata differ.
The tags carry nothing the voice needs, so they are dropped before merging."""
import runpy, sys
import onnx.compose

_merge = onnx.compose.merge_models


def merge_models(m1, m2, *a, **k):
    for m in (m1, m2):
        keep = [p for p in m.metadata_props if not p.key.startswith('onnxsim')]
        del m.metadata_props[:]; m.metadata_props.extend(keep)
    return _merge(m1, m2, *a, **k)


onnx.compose.merge_models = merge_models
sys.argv = ['scripts/export.py', *sys.argv[1:]]
runpy.run_path('scripts/export.py', run_name='__main__')
