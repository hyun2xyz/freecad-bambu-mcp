"""Run inside FreeCAD's Python console to create the example document."""
import FreeCAD as App
import Part

NAME = "PipelinePlate"
if NAME in App.listDocuments():
    raise RuntimeError("refusing to mutate duplicate document: " + NAME)
doc = App.newDocument(NAME)
base = doc.addObject("Part::Box", "PlateBase")
base.Length, base.Width, base.Height = 80, 40, 4
hole = doc.addObject("Part::Cylinder", "HoleTool")
hole.Radius, hole.Height = 5, 4
hole.Placement.Base = App.Vector(40, 20, 0)
result = doc.addObject("Part::Cut", "PlateWithHole")
result.Base, result.Tool = base, hole
doc.recompute()
base.ViewObject.Visibility = False
hole.ViewObject.Visibility = False
result.ViewObject.Visibility = True
import FreeCADGui as Gui
Gui.activeDocument().activeView().viewAxonometric()
Gui.activeDocument().activeView().fitAll()
