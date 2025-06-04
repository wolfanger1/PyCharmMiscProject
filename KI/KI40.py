from panda3d.core import loadPrcFileData
# Setze Konfigurationswerte, damit ein Fenster erzeugt wird
loadPrcFileData("", "window-type onscreen")
loadPrcFileData("", "win-size 800 600")
loadPrcFileData("", "window-title Lager Simulation")

import random
import math
import matplotlib.pyplot as plt  # Matplotlib zum Plotten importieren
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData, GeomNode,
    GeomVertexWriter, GeomLines, Geom, Vec3, ClockObject, TextNode, LineSegs,
    CardMaker, AmbientLight, DirectionalLight
)
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel
from panda3d.ai import AIBehaviors   # Import für AIBehaviors

# globalClock zur Berechnung von dt
globalClock = ClockObject.getGlobalClock()

class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Basis-Parameter
        self.base_speed = 1.5  # m/s
        self.speed_factor = 1.0
        self.max_steering_rate = 90  # Grad pro Sekunde
        self.acceleration = 2.5  # m/s²
        self.braking_deceleration = -2.5  # m/s²

        # Statistiken
        self.sim_clock = 0.0
        self.delivered_packages = 0
        self.max_overall_wait_time = 0.0
        self.total_dwell_time = 0.0
        self.picked_up_count = 0

        self.sim_start_real = globalClock.getFrameTime()

        # Kameraeinstellungen
        self.cam.setPos(0, -60, 30)
        self.cam.lookAt(0, 0, 0)

        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=40, cell_size=1)
        self.draw_coordinate_axes(axis_length=5)

        # Erzeuge Stationen
        station_count = 5
        spacing = 5
        y_start = -((station_count - 1) * spacing) / 2
        self.annahme_stationen = []
        self.abgabe_stationen = []
        for i in range(station_count):
            y = y_start + i * spacing
            pickup_station = self.erzeuge_gitterbox(-9, y, 0, LColor(1, 0, 0, 1))
            self.annahme_stationen.append(pickup_station)
            dropoff_station = self.erzeuge_gitterbox(9, y, 0, LColor(0, 1, 0, 1))
            self.abgabe_stationen.append(dropoff_station)

        # (Zeichne Align-Punkte, Anfahrstationen etc.)
        # ... [Die übrigen Zeichnungs- und Setup-Methoden bleiben hier unverändert] ...

        # Anfahrstationen für Fahrzeuge
        self.anfahrstationen = []
        num_departure = 2
        spacing_departure = 4.0
        start_x = -spacing_departure * (num_departure - 1) / 2
        for i in range(num_departure):
            pos = Vec3(start_x + i * spacing_departure, 15, 0)
            station = self.erzeuge_gitterbox(pos.getX(), pos.getY(), pos.getZ(), LColor(0.8, 0.8, 0, 1))
            self.anfahrstationen.append(station)

        # Fahrzeuge erstellen und mit AI ausstatten
        self.vehicles = []
        self.cargos = {}
        self.current_dropoffs = {}
        for i, start_station in enumerate(self.anfahrstationen):
            vehicle = self.loader.loadModel("models/box")
            vehicle.setScale(2, 1, 0.5)
            if i % 2 == 0:
                vehicle.setColor(LColor(0, 0, 1, 1))
            else:
                vehicle.setColor(LColor(0, 0, 0.8, 1))
            vehicle.setPos(start_station.getPos())
            vehicle.reparentTo(self.render)
            vehicle.setPythonTag("current_speed", 0.0)
            vehicle.setH(0)
            vehicle.setPythonTag("phase", "pickup")
            # Marker und AI setzen:
            self.add_center_marker(vehicle)
            self.add_front_marker(vehicle)
            self.add_y_marker(vehicle)
            self.add_alignment_marker(vehicle)
            self.add_offset_circle(vehicle, offset=Vec3(0.5, 0.5, 0.01), circle_radius=1.5)
            self.setup_ai_for_vehicle(vehicle)  # AI-Behaviors initialisieren
            self.vehicles.append(vehicle)

        # Restliche Logik, GUI, Tasks etc.
        # ... [Die übrigen Methoden zur Logik (Pickup/Dropoff, Slider, etc.) bleiben unverändert] ...

        # Starte den Liefervorgang gestaffelt
        for i, vehicle in enumerate(self.vehicles):
            self.taskMgr.doMethodLater(i * 0.5,
                                       lambda task, v=vehicle: self.start_delivery_cycle(v, v.getPos()),
                                       f"StartDeliveryCycleTask_{i}")

    def setup_ai_for_vehicle(self, vehicle):
        # Initialisiert AIBehaviors für das Fahrzeug (Parameter anpassen, falls nötig)
        ai_behaviors = AIBehaviors(vehicle, 10.0, self.base_speed, 1.0)
        vehicle.setPythonTag("ai_behaviors", ai_behaviors)

    # Die restlichen Methoden (zoom_in, zoom_out, open_graph etc.) bleiben unverändert
    # ...
    # Beispiel: move_vehicle_to mithilfe von AIBehaviors:
    def move_vehicle_to(self, vehicle, target, on_complete):
        ai_behaviors = vehicle.getPythonTag("ai_behaviors")
        if ai_behaviors is None:
            print("Kein AI-Behaviors-Objekt vorhanden, verwende manuelle Navigation.")
            # Fallback (nicht implementiert, da hier ausschließlich AI-Navigation genutzt wird)
            return
        # Starte den Pfadfindungs-Behavior
        ai_behaviors.pathFindTo(target)
        def check_arrival(task):
            if (target - vehicle.getPos()).length() < 0.5:
                ai_behaviors.clearBehaviors()
                on_complete()
                return Task.done
            return Task.cont
        self.taskMgr.add(check_arrival, f"check_arrival_{id(vehicle)}")

    # Die übrigen Methoden (update_sim_clock, add_center_marker, etc.) kommen hierher
    # ...

    # Beispiel für eine einfache Lichtquelle:
    def erzeuge_licht(self):
        alight = AmbientLight("ambient_light")
        alight.setColor((0.5, 0.5, 0.5, 1))
        self.render.setLight(self.render.attachNewNode(alight))
        dlight = DirectionalLight("directional_light")
        dlight.setColor((1, 1, 1, 1))
        dlightNP = self.render.attachNewNode(dlight)
        dlightNP.setPos(10, -10, 10)
        self.render.setLight(dlightNP)

    # Beispiel für Bodenraster:
    def erzeuge_bodenraster(self, center_extent=40, cell_size=1):
        vertex_format = GeomVertexFormat.getV3()
        vdata = GeomVertexData("grid", vertex_format, Geom.UHStatic)
        writer = GeomVertexWriter(vdata, "vertex")
        lines = GeomLines(Geom.UHStatic)
        n_vertices = 0
        min_line, max_line = -center_extent - 0.5, center_extent + 0.5
        y = min_line
        while y <= max_line:
            writer.addData3(min_line, y, 0)
            writer.addData3(max_line, y, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            y += cell_size
        x = min_line
        while x <= max_line:
            writer.addData3(x, min_line, 0)
            writer.addData3(x, max_line, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            x += cell_size
        lines.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(lines)
        node = GeomNode("grid")
        node.addGeom(geom)
        np_grid = self.render.attachNewNode(node)
        np_grid.setColor(0.7, 0.7, 0.7, 1)
        return np_grid

    # Weitere Methoden zur Logik, Markierung, Alignment, etc. folgen hier...
    # [Die übrigen Methoden bleibe ich hier gekürzt – in deinem Code sind sie vorhanden.]

app = LagerSimulation()
app.run()
