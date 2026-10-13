"""Execute the generated export script with offline FreeCAD stand-ins."""
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from freecad_bambu_mcp.cad import FreeCADClient


class Shape:
    def __init__(self, bounds=(0, 0, 0, 90, 50, 2.6), volume=8570.38,
                 solids=1, null=False, valid=True):
        self.reads = Counter()
        self.bounds, self.volume, self.solids = bounds, volume, solids
        self.null, self.valid = null, valid

    def isNull(self):
        return self.null

    def isValid(self):
        return self.valid

    @property
    def Solids(self):
        self.reads['Solids'] += 1
        return [object() for _ in range(self.solids)]

    @property
    def Volume(self):
        self.reads['Volume'] += 1
        return self.volume

    @property
    def BoundBox(self):
        self.reads['BoundBox'] += 1
        return SimpleNamespace(**dict(zip(
            ('XMin', 'YMin', 'ZMin', 'XMax', 'YMax', 'ZMax'), self.bounds)))


class Feature:
    def __init__(self, shape):
        self.shape = shape
        self.shape_reads = 0

    @property
    def Shape(self):
        self.shape_reads += 1
        return self.shape


def executing_client(objects):
    """Use actual generated Python; simulate only the FreeCAD/native boundary."""
    document = SimpleNamespace(
        getObject=objects.get,
        recompute=Mock(),
        saveCopy=Mock(side_effect=lambda path: Path(path).write_bytes(b'FCStd')),
        FileName='original.FCStd',
    )
    mesh = SimpleNamespace(export=Mock(
        side_effect=lambda items, path: Path(path).write_bytes(b'STL')))
    part = SimpleNamespace(export=Mock(
        side_effect=lambda items, path: Path(path).write_bytes(b'STEP')))
    modules = {
        'FreeCAD': SimpleNamespace(getDocument=Mock(return_value=document)),
        'Mesh': mesh, 'Part': part,
    }

    def execute(name, source):
        assert name == 'execute_code'
        stream = io.StringIO()
        try:
            with patch.dict(sys.modules, modules), redirect_stdout(stream):
                exec(compile(source, '<export RPC>', 'exec'), {})
        except Exception as exc:
            return {'success': False, 'error': str(exc)}
        return {'success': True, 'message': stream.getvalue()}

    client = FreeCADClient()
    client._call = Mock(side_effect=execute)
    return client, document, mesh, part


def test_export_caches_native_measurements_and_preserves_source(tmp_path):
    card = Feature(Shape())
    other = Feature(Shape(bounds=(-2, 5, -1, 4, 8, 3), volume=25, solids=2))
    client, document, mesh, part = executing_client({'Card': card, 'Other': other})

    result = client.export('BusinessCard', ['Card', 'Other'], tmp_path)

    assert result['success'], result
    assert result['bounds_mm'] == [-2, 0, -1, 90, 50, 3]
    assert result['volume_mm3'] == pytest.approx(8595.38)
    assert result['solid_count'] == 3
    assert result['paths']['model'] == result['paths']['fcstd']
    for feature in (card, other):
        assert feature.shape_reads == 1
        assert feature.shape.reads == {'Solids': 1, 'Volume': 1, 'BoundBox': 1}
    client._call.assert_called_once()
    document.recompute.assert_called_once_with()
    document.saveCopy.assert_called_once_with(str(tmp_path / 'model.FCStd'))
    assert document.FileName == 'original.FCStd'
    mesh.export.assert_called_once_with([card, other], str(tmp_path / 'model.stl'))
    part.export.assert_called_once_with([card, other], str(tmp_path / 'model.step'))


@pytest.mark.parametrize('feature', [
    None, SimpleNamespace(), Feature(Shape(null=True)),
    Feature(Shape(valid=False)), Feature(Shape(solids=0)),
    Feature(Shape(volume=0)), Feature(Shape(volume=-1)),
    Feature(Shape(volume=float('nan'))),
    Feature(Shape(bounds=(0, 0, 0, float('inf'), 50, 2.6))),
])
def test_invalid_geometry_is_rejected_before_writing_files(tmp_path, feature):
    client, document, mesh, part = executing_client({'Bad': feature})
    result = client.export('Card', ['Bad'], tmp_path)
    assert not result['success']
    assert 'invalid' in result['error']
    document.saveCopy.assert_not_called()
    mesh.export.assert_not_called()
    part.export.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('count', [None, 0, -1, True, 1.5, '1', float('inf')])
def test_export_rejects_malformed_solid_count(tmp_path, count):
    evidence = {'bounds': [0, 0, 0, 90, 50, 2.6], 'volume': 8570.38,
                'solid_count': count}
    client = FreeCADClient()
    client._call = Mock(return_value={
        'success': True, 'message': '__MCP_EXPORT__' + json.dumps(evidence)})
    result = client.export('Card', ['Card'], tmp_path)
    assert not result['success']
    assert result['error'] == 'invalid export measurements'


def test_existing_export_is_preserved_without_rpc(tmp_path):
    existing = tmp_path / 'model.stl'
    existing.write_bytes(b'original')
    client, _, _, _ = executing_client({})
    result = client.export('Card', ['Card'], tmp_path)
    assert not result['success']
    assert existing.read_bytes() == b'original'
    client._call.assert_not_called()
