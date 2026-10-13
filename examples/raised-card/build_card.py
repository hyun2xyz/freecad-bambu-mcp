"""Trusted, editable FreeCAD business card. See the adjacent README.md. No printer/network calls.

Built-in feature tree: spreadsheet -> box/fillet, ShapeStrings -> Extrusions,
folder sketch -> Extrusion, then one MultiFuse. Text is never anisotropically scaled.
"""
from pathlib import Path
import json, time
import FreeCAD as App
import Part, Draft, Sketcher, Spreadsheet

# FreeCADMCP executes a source string without __file__. A local wrapper can
# provide CARD_FONT_DIR; ordinary file/macro execution uses the adjacent fonts.
font_dir = globals().get('CARD_FONT_DIR')
if font_dir is None:
    if '__file__' not in globals():
        raise RuntimeError('Set CARD_FONT_DIR to this example\'s fonts directory; see README.md')
    font_dir = Path(__file__).resolve().parent / 'fonts'
ASSETS = Path(font_dir).expanduser().resolve()
for font_name in ('Roboto-Bold.ttf', 'Roboto-Black.ttf'):
    if not (ASSETS / font_name).is_file():
        raise FileNotFoundError(str(ASSETS / font_name))
DOC = 'IndexOpensourceCardV01'
if DOC in App.listDocuments():
    raise RuntimeError('Document already exists; inspect it before rerunning')
started = time.perf_counter()
doc = App.newDocument(DOC)
doc.Label = 'index.opensource — 90 × 50 mm raised card v01'
params = doc.addObject('Spreadsheet::Sheet', 'Parameters')
for row, (label, value, alias) in enumerate([
    ('Width', '90 mm', 'Width'), ('Height', '50 mm', 'Height'),
    ('Base thickness', '1.8 mm', 'BaseThickness'),
    ('Relief above base', '0.8 mm', 'ReliefHeight'),
    ('Embed relief into base', '0.1 mm', 'EmbedDepth'),
    ('Corner radius', '2.4 mm', 'CornerRadius'),
], 1):
    params.set('A' + str(row), label)
    params.set('B' + str(row), value)
    params.setAlias('B' + str(row), alias)
base = doc.addObject('Part::Box', 'BaseBlank')
for prop, expr in [('Length','Width'),('Width','Height'),('Height','BaseThickness')]:
    base.setExpression(prop, 'Parameters.' + expr)
doc.recompute()
vertical_edges = [(i, 2.4, 2.4) for i,e in enumerate(base.Shape.Edges,1)
                  if e.BoundBox.ZLength > 1.79 and e.BoundBox.XLength < 1e-7 and e.BoundBox.YLength < 1e-7]
rounded = doc.addObject('Part::Fillet', 'RoundedCardBase')
rounded.Base = base
rounded.Edges = vertical_edges
if App.GuiUp: base.Visibility = False

lines = [
    ('Account', 'index.opensource', 4.8, 23.0, 38.5, 'Roboto-Bold.ttf'),
    ('Creative', 'Creative open source for', 3.2, 5.0, 29.2, 'Roboto-Black.ttf'),
    ('Makers', 'sustainable makers', 3.2, 5.0, 23.5, 'Roboto-Black.ttf'),
    ('Archive', 'Explainers + source archive', 3.2, 5.0, 17.8, 'Roboto-Black.ttf'),
    ('Authors', 'by @hyun2xyz @hyun2ai', 3.0, 5.0, 11.2, 'Roboto-Black.ttf'),
    ('Website', 'indexopensource.com', 3.8, 5.0, 4.7, 'Roboto-Bold.ttf'),
]
text_sources = []
for key, text, size, x, y, font in lines:
    obj = Draft.makeShapeString(String=text, FontFile=str(ASSETS/font), Size=size, Tracking=0)
    obj.Label = key + ' | ' + text
    text_sources.append(obj)
doc.recompute()
extrusions = []
metrics = []
for line, ss in zip(lines, text_sources):
    key, text, size, x, y, font = line
    bb = ss.Shape.BoundBox
    ss.Placement.Base = App.Vector(x-bb.XMin, y-bb.YMin, 1.7)
    ex = doc.addObject('Part::Extrusion', key+'Relief')
    ex.Base = ss
    ex.DirMode = 'Normal'
    ex.Dir = App.Vector(0,0,1)
    ex.setExpression('LengthFwd', 'Parameters.ReliefHeight + Parameters.EmbedDepth')
    ex.LengthRev = 0
    ex.Solid = True
    if App.GuiUp: ss.Visibility = False
    extrusions.append(ex)
    metrics.append({'name':key,'text':text,'cap_height_mm':size,'width_mm':bb.XLength,'height_mm':bb.YLength,'x_mm':x,'y_mm':y})

# Folder silhouette reconstructed from the supplied image proportions.
folder = doc.addObject('Sketcher::SketchObject', 'FolderOutline')
folder.Placement.Base = App.Vector(5,36.5,1.7)
V = lambda x,y: App.Vector(x,y,0)
geom = [
    Part.LineSegment(V(1.2,0),V(11.6,0)),
    Part.Arc(V(11.6,0),V(12.448528,0.351472),V(12.8,1.2)),
    Part.LineSegment(V(12.8,1.2),V(12.8,7.5)),
    Part.Arc(V(12.8,7.5),V(12.448528,8.348528),V(11.6,8.7)),
    Part.LineSegment(V(11.6,8.7),V(6.3,8.7)),
    Part.LineSegment(V(6.3,8.7),V(4.9,9.9)),
    Part.LineSegment(V(4.9,9.9),V(1.2,9.9)),
    Part.Arc(V(1.2,9.9),V(0.351472,9.548528),V(0,8.7)),
    Part.LineSegment(V(0,8.7),V(0,1.2)),
    Part.Arc(V(0,1.2),V(0.351472,0.351472),V(1.2,0)),
]
for g in geom:
    i = folder.addGeometry(g,False)
    folder.addConstraint(Sketcher.Constraint('Block',i))
logo = doc.addObject('Part::Extrusion','FolderLogoRelief')
logo.Base = folder
logo.Dir = App.Vector(0,0,1)
logo.setExpression('LengthFwd','Parameters.ReliefHeight + Parameters.EmbedDepth')
logo.Solid = True
if App.GuiUp: folder.Visibility = False

def bar(a,b,width=0.7):
    d = b.sub(a); n = App.Vector(-d.y,d.x,0); n.normalize(); n.multiply(width/2)
    pts=[a.add(n),b.add(n),b.sub(n),a.sub(n)]
    return Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(App.Vector(0,0,0.9))
tip=App.Vector(62.2,18.15,1.7)
shaft=bar(tip,App.Vector(65,20.95,1.7))
horizontal=bar(tip,App.Vector(64.5,18.15,1.7))
vertical=bar(tip,App.Vector(62.2,20.45,1.7))
arrow=doc.addObject('Part::Feature','ArchiveArrowRelief')
arrow.Shape=shaft.fuse([horizontal,vertical]).removeSplitter()

doc.recompute()
parts=[rounded]+extrusions+[logo,arrow]
for obj in parts:
    if obj.Shape.isNull() or not obj.Shape.isValid() or not obj.Shape.Solids:
        raise ValueError('Invalid source solid: '+obj.Name)
    if obj != rounded and obj.Shape.common(rounded.Shape).Volume <= 0:
        raise ValueError('Relief does not intersect base: '+obj.Name)
for m in metrics:
    if m['x_mm'] < 4 or m['x_mm']+m['width_mm'] > 86 or m['y_mm'] < 4 or m['y_mm']+m['height_mm'] > 47:
        raise ValueError('Text outside safe card margins: '+m['text'])
card=doc.addObject('Part::MultiFuse','PrintableCard')
card.Shapes=parts
card.Refine=True
doc.recompute()
shape=card.Shape
if not shape.isValid() or not shape.isClosed() or len(shape.Solids)!=1:
    raise ValueError('Printable card must be one closed valid solid')
if App.GuiUp:
    import FreeCADGui as Gui
    for obj in parts:
        obj.Visibility = False
    card.ViewObject.ShapeColor = (0.87, 0.84, 0.78)
    card.ViewObject.LineColor = (0.25, 0.23, 0.20)
    card.ViewObject.DisplayMode = 'Flat Lines'
    card.ViewObject.Deviation = 0.05
    card.ViewObject.AngularDeflection = 10
    Gui.activeDocument().activeView().viewTop()
    Gui.activeDocument().activeView().fitAll()

# Keep exports in the pipeline, or use the controlled tessellation in README.md.
report = {
    'document': DOC, 'object': card.Name, 'freecad_version': App.Version()[:3],
    'dimensions_mm': [shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength],
    'base_mm': 1.8, 'relief_mm': 0.8, 'intersection_mm': 0.1,
    'valid': shape.isValid(), 'closed': shape.isClosed(), 'solid_count': len(shape.Solids),
    'volume_mm3': shape.Volume, 'text_lines': metrics,
    'build_seconds': time.perf_counter() - started,
}
print('__RAISED_CARD__' + json.dumps(report, ensure_ascii=False))
