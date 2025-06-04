import random
import math
import tkinter as tk  # Für das extra Fenster der Auftragsübersicht
from tkinter import ttk  # Für die tabellarische Darstellung (Treeview)
import matplotlib.pyplot as plt  # Für interaktive Graphen

from panda3d.core import (
    LColor,
    GeomVertexFormat,
    GeomVertexData,
    GeomVertexWriter,
    GeomLines,
    GeomTriangles,
    Geom,
    GeomNode,
    ClockObject,
    AmbientLight,
    DirectionalLight,
    Vec2,
    Vec3,
    LineSegs,
    TextNode,
    CardMaker,
    NodePath,
    RenderModeAttrib
)
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel

from direct.task.TaskManagerGlobal import taskMgr


from functools import partial






class LagerSimulation(ShowBase):
    def __init__(self):
            super().__init__()

            # Basis-Simulationsvariablen
            self.sim_clock = 0.0
            self.speed_factor = 1.0
            self.current_speed = 1.5  # Wird in update_vehicle genutzt
            self.state_timer = 0.0

            # Kennzahlen (KPIs)
            self.delivered_packages = 0
            self.max_overall_wait_time = 0.0
            self.total_dwell_time = 0.0
            self.picked_up_count = 0

            # Paketspawning an den Annahmestationen:
            # Mapping: station (Dummy-Node) -> (Paket, Spawnzeit, Timer Node)
            self.pickup_packages = {}
            self.last_removed = {}

            # Fahrzeug-spezifische Zuordnung: Fahrzeug -> transportiertes Paket
            self.cargos = {}

            # NEU: Initialisiere die belegten Annahmestationen
            self.occupied_pickups = set()  # Oder: [] für eine Liste

            # Graph-Daten (Sim-Zeit, Pakete pro Minute, durchschnittliche Liegedauer)
            self.graph_data = []
            self.graph_opened = False

            # Auftragsverwaltung: Speichere alle Aufträge (für die Anzeige) sowie in
            # einer Queue (Liste) zur sequentiellen Abarbeitung.
            self.orders = {}
            self.orders_queue = []
            self.next_order_id = 1

            # Tkinter-Fenster für Auftragsübersicht
            self.order_win = None
            self.order_tree = None

            # Umgebung initialisieren
            self.draw_origin()
            self.cam.setPos(11, -80, 40)
            self.cam.lookAt(11, 30, 0)
            self.erzeuge_licht()
            self.erzeuge_bodenraster(center_extent=70, cell_size=1)
            self.create_wall()
            self.create_annahme_stations()
            self.create_abgabe_stations()  # Hier wird auch self.abgabe_stations angelegt.
            self.create_garagen_stations()

            for station in self.annahme_stations:
                self.spawn_package_at_station(station)

            # Fahrzeuge in den Garagen erstellen (genau 5 Fahrzeuge)
            self.create_garage_vehicles()

            # NEU: Testvariablen (werden nicht mehr aktiv über diesen globalen Mechanismus gesteuert)
            self.first_vehicle_order_state = "idle"
            self.attached_package = None
            self.current_order = None  # Der aktuell abgearbeitete Auftrag (wird durch Fahrzeuge individuell genutzt)

            # UI – Slider und Info-Anzeige
            self.speed_slider = DirectSlider(
                range=(0.1, 10.0),
                value=self.speed_factor,
                pageSize=0.1,
                command=self.update_simulation_speed,
                pos=(0, 0, -0.85),
                scale=0.3
            )
            self.speed_label = DirectLabel(
                text=f"Sim Time Factor: {self.speed_factor:.1f}",
                pos=(0, 0, -0.75),
                scale=0.07
            )
            self.info_label = DirectLabel(
                text="Laufzeit: 0.0s",
                pos=(1.2, 0, 0.8),
                scale=0.07,
                frameColor=(0, 0, 0, 0)
            )

            # Tastenzuordnungen
            self.accept("wheel_up", self.zoom_in)
            self.accept("wheel_down", self.zoom_out)
            self.accept("g", self.open_graph)
            self.accept("a", self.show_order_list)
            self.accept("d", self.deliver_first_order)
            # Taste C öffnet das Fahrzeug-Kontrollfenster
            self.accept("c", self.show_vehicle_control)

            # Task-Manager
            self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
            self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
            self.taskMgr.add(self.check_and_spawn_packages, "CheckSpawnPackagesTask")
            self.taskMgr.add(self.update_package_timers, "UpdatePackageTimersTask")
            self.taskMgr.add(self.update_order_status, "UpdateOrderStatusTask")
            self.taskMgr.doMethodLater(1, self.update_graph_data, "UpdateGraphDataTask")

    # ---------------------------
    # SIMULATION UND UI-METHODEN
    # ---------------------------
    def update_sim_clock(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.sim_clock += dt * self.speed_factor
        return Task.cont

    def update_info_display(self, task):
        tot = self.sim_clock
        h = int(tot // 3600)
        m = int((tot % 3600) // 60)
        s = tot % 60
        formatted = f"{h}h {m}m {s:.1f}s"
        current_max = 0.0
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_clock - spawn_time
            if elapsed > current_max:
                current_max = elapsed
        self.max_overall_wait_time = max(self.max_overall_wait_time, current_max)
        avg_dwell = self.total_dwell_time / self.picked_up_count if self.picked_up_count > 0 else 0.0
        ppm = self.delivered_packages / (self.sim_clock / 60) if self.sim_clock > 0 else 0
        self.info_label['text'] = (
            f"Laufzeit: {formatted}\n"
            f"Abgegebene Pakete: {self.delivered_packages}\n"
            f"Pakete pro Minute: {ppm:.1f}\n"
            f"Liegedauer (aktuell): {current_max:.1f}s\n"
            f"Liegedauer (maximal): {self.max_overall_wait_time:.1f}s\n"
            f"Durchschn. Liegedauer: {avg_dwell:.1f}s"
        )
        return Task.cont

    def update_simulation_speed(self, speed_factor=None):
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

    def zoom_in(self):
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = max(10, current_fov - 5)
        lens.setFov(new_fov)
        print(f"Zoom In: FOV von {current_fov} auf {new_fov}")

    def zoom_out(self):
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = min(100, current_fov + 5)
        lens.setFov(new_fov)
        print(f"Zoom Out: FOV von {current_fov} auf {new_fov}")

    def update_vehicle(self, task):
        # dt jetzt skaliert mit der Simulationsgeschwindigkeit
        dt = ClockObject.getGlobalClock().getDt() * self.speed_factor
        pos = self.vehicle.getPos()
        forward = self.vehicle.getQuat().getForward()

        target_speed = 1.5
        acc_rate = 2.0

        if self.current_speed < target_speed:
            self.current_speed = min(self.current_speed + acc_rate * dt, target_speed)
        elif self.current_speed > target_speed:
            self.current_speed = max(self.current_speed - acc_rate * dt, target_speed)

        new_pos = pos + forward * self.current_speed * dt
        self.vehicle.setPos(new_pos)
        return Task.cont

    # ---------------------------
    # METHODEN FÜR RASTER, LICHT, MAUER, URSPRUNG
    # ---------------------------
    def erzeuge_bodenraster(self, center_extent=70, cell_size=1):
        vertex_format = GeomVertexFormat.getV3()
        vdata = GeomVertexData("grid", vertex_format, Geom.UHStatic)
        writer = GeomVertexWriter(vdata, "vertex")
        lines = GeomLines(Geom.UHStatic)
        n_vertices = 0
        min_line = -center_extent - 0.5
        max_line = center_extent + 0.5
        y = min_line
        while y <= max_line:
            writer.addData3f(min_line, y, 0)
            writer.addData3f(max_line, y, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            y += cell_size
        x = min_line
        while x <= max_line:
            writer.addData3f(x, min_line, 0)
            writer.addData3f(x, max_line, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            x += cell_size
        lines.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(lines)
        node = GeomNode("grid")
        node.addGeom(geom)
        np_grid = self.render.attachNewNode(node)
        np_grid.setColor(LColor(0.7, 0.7, 0.7, 1))
        return np_grid

    def erzeuge_licht(self):
        alight = AmbientLight("ambient_light")
        alight.setColor((0.5, 0.5, 0.5, 1))
        alight_np = self.render.attachNewNode(alight)
        self.render.setLight(alight_np)
        dlight = DirectionalLight("directional_light")
        dlight.setColor((1, 1, 1, 1))
        dlight_np = self.render.attachNewNode(dlight)
        dlight_np.setPos(10, -10, 10)
        self.render.setLight(dlight_np)

    def create_wall(self):
        p1 = Vec3(0, 0, 0)
        p2 = Vec3(0, 60, 0)
        p3 = Vec3(22, 60, 0)
        p4 = Vec3(22, 0, 0)
        self.add_wall_segment(p1, p2)
        self.add_wall_segment(p2, p3)
        self.add_wall_segment(p3, p4)
        self.add_wall_segment(p4, p1)

    def add_wall_segment(self, start, end, height=2.0, thickness=0.5):
        seg_vector = end - start
        length = seg_vector.length()
        if length == 0:
            return
        d = seg_vector.normalized()
        outward = Vec3(-d.getY(), d.getX(), 0)
        center = (start + end) * 0.5 + outward * (thickness / 2.0)
        center.setZ(height / 2.0)
        angle = math.degrees(math.atan2(seg_vector.getY(), seg_vector.getX()))
        wall_np = self.render.attachNewNode("wall_np")
        wall = self.loader.loadModel("models/box")
        bounds = wall.getTightBounds()
        if bounds:
            low, high = bounds
            box_center = (low + high) * 0.5
            wall.setPos(-box_center)
        wall.reparentTo(wall_np)
        wall_np.setScale(length, thickness, height)
        wall_np.setPos(center)
        wall_np.setH(angle)
        wall_np.setTextureOff(1)
        wall_np.setColor(LColor(0.5, 0.5, 0.5, 1))

    def draw_origin(self):
        ls = LineSegs()
        ls.setThickness(2)
        ls.setColor(LColor(1, 0, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(1, 0, 0)
        ls.setColor(LColor(0, 1, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 1, 0)
        ls.setColor(LColor(0, 0, 1, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 0, 1)
        self.render.attachNewNode(ls.create())

    # -----------------------------------
    # STATIONSOBJEKTE UND ZUORDNUNG
    # -----------------------------------
    def create_annahme_station(self, pos):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(0, 1, 0, 1))
        v0 = pos + Vec3(0, 0, 0)
        v1 = pos + Vec3(1, 0, 0)
        v2 = pos + Vec3(1, 1, 0)
        v3 = pos + Vec3(0, 1, 0)
        v4 = pos + Vec3(0, 0, 1)
        v5 = pos + Vec3(1, 0, 1)
        v6 = pos + Vec3(1, 1, 1)
        v7 = pos + Vec3(0, 1, 1)
        ls.moveTo(v0)
        ls.drawTo(v1)
        ls.moveTo(v2)
        ls.drawTo(v3)
        ls.moveTo(v3)
        ls.drawTo(v0)
        ls.moveTo(v4)
        ls.drawTo(v5)
        ls.moveTo(v6)
        ls.drawTo(v7)
        ls.moveTo(v7)
        ls.drawTo(v4)
        ls.moveTo(v0)
        ls.drawTo(v4)
        ls.moveTo(v3)
        ls.drawTo(v7)
        return self.render.attachNewNode(ls.create())

    def create_annahme_stations(self):
        """
        Erzeugt die Annahmestationen und erstellt für jede Station:
          - Einen weißen Marker zur Orientierung
          - Einen grünen Punkt (optional)
          - Eine weiße Linie, an deren Endpunkt ein blauer Marker als Ziel in der "Translate‑Phase" dient

        Zusätzlich wird ein Dictionary self.station_blue_dots aufgebaut, in dem jedem Annahmestations‑Node
        der zugehörige blaue Marker zugeordnet wird. Außerdem wird für die erste Station die globale Variable
        self.station_white_direction festgelegt.
        """
        station_points = [
            Vec3(0, 5, 0), Vec3(0, 10, 0), Vec3(0, 15, 0),
            Vec3(0, 20, 0), Vec3(0, 25, 0), Vec3(0, 30, 0),
            Vec3(0, 35, 0), Vec3(0, 40, 0), Vec3(0, 45, 0),
            Vec3(0, 50, 0)
        ]
        self.annahme_stations = []
        self.station_blue_dots = {}

        for i, pt in enumerate(station_points, start=1):
            # Erstelle die Basisstation (zum Beispiel als Rahmen)
            self.create_annahme_station(pt)
            station_dummy = self.render.attachNewNode(f"annahme_station_{i}")
            station_dummy.setPos(pt)
            self.annahme_stations.append(station_dummy)

            # Berechne den Mittelpunkt der Station
            center = pt + Vec3(0.5, 0.5, 0.5)

            # Erzeuge den weißen Marker als Orientierung
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)

            # Erzeuge den grünen Punkt (optional)
            green_dot = self.loader.loadModel("models/misc/sphere")
            green_dot.setScale(0.1)
            green_dot.setColor(LColor(0, 1, 0, 1))
            green_dot.setPos(center + Vec3(0, 0, -0.5))
            green_dot.reparentTo(self.render)

            # Zeichne die weiße Linie: Sie beginnt bei center + Vec3(0, 0, -0.5) und verläuft 3 Meter in X‑Richtung.
            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, -0.5)
            end_line = start_line + Vec3(3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())

            # Erzeuge den blauen Marker, der als Ziel in der Translate‑Phase dient
            blue_dot = self.loader.loadModel("models/misc/sphere")
            blue_dot.setScale(0.1)
            blue_dot.setColor(LColor(0, 0, 1, 1))
            blue_dot.setPos(end_line)
            blue_dot.reparentTo(self.render)

            # Speichere den blauen Marker im Dictionary, sodass er später erzeugt werden kann
            self.station_blue_dots[station_dummy] = blue_dot

            # Optionale Textanzeige der Stationsnummer
            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 1.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

            # Zusätzliche Markierungen (Kreuze) – falls benötigt:
            v0 = pt + Vec3(0, 0, 0)
            v1 = pt + Vec3(1, 0, 0)
            v2 = pt + Vec3(1, 1, 0)
            v3 = pt + Vec3(0, 1, 0)
            v4 = pt + Vec3(0, 0, 1)
            v5 = pt + Vec3(1, 0, 1)
            v6 = pt + Vec3(1, 1, 1)
            v7 = pt + Vec3(0, 1, 1)
            self.add_cross_on_face([v0, v3, v7, v4], color=LColor(0, 1, 0, 1))
            self.add_cross_on_face([v0, v1, v5, v4], color=LColor(0, 1, 0, 1))
            self.add_cross_on_face([v3, v2, v6, v7], color=LColor(0, 1, 0, 1))

            # Für die erste Station (oder den ersten relevanten Pickup) setzen wir globale Referenzen,
            # die in vehicle_order_task benötigt werden.
            if i == 1:
                self.blue_dot = blue_dot
                self.station_green_dot = green_dot
                # Berechne den Mittelpunkt der weißen Linie als Referenz (optional)
                self.white_line_center = (start_line + end_line) * 0.5
                line_vec = end_line - start_line
                if line_vec.length() != 0:
                    self.station_white_direction = Vec2(line_vec.getX(), line_vec.getY()).normalized()
                else:
                    self.station_white_direction = Vec2(1, 0)  # Fallback-Wert

    def create_abgabe_station(self, pos):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(1, 0, 0, 1))
        v0 = pos + Vec3(0, 0, 0)
        v1 = pos + Vec3(1, 0, 0)
        v2 = pos + Vec3(1, 1, 0)
        v3 = pos + Vec3(0, 1, 0)
        v4 = pos + Vec3(0, 0, 1)
        v5 = pos + Vec3(1, 0, 1)
        v6 = pos + Vec3(1, 1, 1)
        v7 = pos + Vec3(0, 1, 1)
        ls.moveTo(v0)
        ls.drawTo(v1)
        ls.moveTo(v1)
        ls.drawTo(v2)
        ls.moveTo(v2)
        ls.drawTo(v3)
        ls.moveTo(v4)
        ls.drawTo(v5)
        ls.moveTo(v5)
        ls.drawTo(v6)
        ls.moveTo(v6)
        ls.drawTo(v7)
        ls.moveTo(v1)
        ls.drawTo(v5)
        ls.moveTo(v2)
        ls.drawTo(v6)
        return self.render.attachNewNode(ls.create())

    def create_abgabe_stations(self):
        station_points = [
            Vec3(21, 5, 0), Vec3(21, 10, 0), Vec3(21, 15, 0),
            Vec3(21, 20, 0), Vec3(21, 25, 0), Vec3(21, 30, 0),
            Vec3(21, 35, 0), Vec3(21, 40, 0), Vec3(21, 45, 0),
            Vec3(21, 50, 0)
        ]
        self.abgabe_stations = []  # Liste der Abgabestationen
        self.abgabe_blue_dots = []  # Liste zum Speichern der blauen Marker für die Abgabe

        for i, pt in enumerate(station_points, start=1):
            # Erstelle die Basiskonstruktion der Abgabestation
            node = self.create_abgabe_station(pt)
            self.abgabe_stations.append(node)

            # Berechne den Mittelpunkt der Station
            center = pt + Vec3(0.5, 0.5, 0.5)

            # Marker am Zentrum (weiß)
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)

            # Grüner Punkt: center + Vec3(0, 0, -0.5)
            green_dot = self.loader.loadModel("models/misc/sphere")
            green_dot.setScale(0.1)
            green_dot.setColor(LColor(0, 1, 0, 1))
            green_dot.setPos(center + Vec3(0, 0, -0.5))
            green_dot.reparentTo(self.render)

            # Weiße Linie: Startet bei center + Vec3(0, 0, -0.5)
            # und verläuft 3 Meter in negativer X-Richtung
            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, -0.5)
            end_line = start_line + Vec3(-3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())

            # Blauer Punkt: wird an der Endposition der Linie erzeugt
            blue_dot = self.loader.loadModel("models/misc/sphere")
            blue_dot.setScale(0.1)
            blue_dot.setColor(LColor(0, 0, 1, 1))
            blue_dot.setPos(end_line)
            blue_dot.reparentTo(self.render)
            # Speichere den blauen Marker für spätere Navigation der Abgabestation
            self.abgabe_blue_dots.append(blue_dot)

            # Anzeige der Stationsnummer (textuell)
            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x - 0.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

            # Zusätzliche Markierungen (Kreuze) auf der Station
            v0 = pt + Vec3(0, 0, 0)
            v1 = pt + Vec3(1, 0, 0)
            v2 = pt + Vec3(1, 1, 0)
            v3 = pt + Vec3(0, 1, 0)
            v4 = pt + Vec3(0, 0, 1)
            v5 = pt + Vec3(1, 0, 1)
            v6 = pt + Vec3(1, 1, 1)
            v7 = pt + Vec3(0, 1, 1)
            self.add_cross_on_face([v1, v2, v6, v5], color=LColor(1, 0, 0, 1))
            self.add_cross_on_face([v0, v1, v5, v4], color=LColor(1, 0, 0, 1))
            self.add_cross_on_face([v3, v2, v6, v7], color=LColor(1, 0, 0, 1))

    def create_garage_station(self, pos):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(0, 0, 1, 1))
        v0 = pos + Vec3(0, 0, 0)
        v1 = pos + Vec3(1, 0, 0)
        v2 = pos + Vec3(1, 2, 0)
        v3 = pos + Vec3(0, 2, 0)
        v4 = pos + Vec3(0, 0, 3)
        v5 = pos + Vec3(1, 0, 3)
        v6 = pos + Vec3(1, 2, 3)
        v7 = pos + Vec3(0, 2, 3)
        edges = [
            (v0, v1), (v1, v2), (v2, v3), (v3, v0),
            (v4, v5), (v5, v6), (v6, v7), (v7, v4),
            (v0, v4), (v1, v5), (v2, v6), (v3, v7)
        ]
        for p, q in edges:
            if p.getY() == pos.getY() and q.getY() == pos.getY():
                continue
            ls.moveTo(p)
            ls.drawTo(q)
        node = self.render.attachNewNode(ls.create())
        self.add_cross_on_face([v3, v2, v6, v7], color=LColor(0, 0, 1, 1))
        self.add_cross_on_face([v0, v3, v7, v4], color=LColor(0, 0, 1, 1))
        self.add_cross_on_face([v1, v2, v6, v5], color=LColor(0, 0, 1, 1))
        return node

    def add_garage_roof(self, pos):
        cm = CardMaker("garage_roof")
        cm.setFrame(0, 1, 0, 2)
        roof = self.render.attachNewNode(cm.generate())
        roof.setHpr(0, -90, 0)
        roof.setPos(pos.x, pos.y, pos.z + 3)
        roof.setColor(LColor(0, 0, 1, 1))
        return roof

    def create_garagen_stations(self):
        station_points = [
            Vec3(3, 58, 0), Vec3(7, 58, 0), Vec3(11, 58, 0),
            Vec3(15, 58, 0), Vec3(19, 58, 0)
        ]
        self.garagen_stations = []
        self.garagen_parking_points = []
        for i, pt in enumerate(station_points, start=1):
            self.create_garage_station(pt)
            self.add_garage_roof(pt)
            self.garagen_stations.append(pt)
            # ParkpunktGarage: Verschoben um 0.5 in negativer Y-Richtung:
            center = pt + Vec3(0.5, 0.5, 1.5)
            ParkpunktGarage = center + Vec3(0, 0, 0.7)
            self.garagen_parking_points.append(ParkpunktGarage)
            tn = TextNode("garage_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 0.5, pt.y - 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

    def create_garage_vehicles(self):
        self.garage_vehicles = []
        vehicle_id_counter = 1
        for park in self.garagen_parking_points:
            veh = self.create_vehicle(park_point=park)
            veh.setH(veh.getH() + 180)
            intersection = Vec3(0.5, 0.05, 1.0)
            newPos = park - veh.getQuat().xform(intersection)
            newPos.setZ(0)
            veh.setPos(newPos)

            # Fahrzeuge starten zunächst im Standby (idle)
            veh.setPythonTag("current_order", None)
            veh.setPythonTag("order_state", "idle")
            veh.setPythonTag("package_attached", False)
            veh.setPythonTag("vehicle_id", vehicle_id_counter)
            vehicle_id_counter += 1

            # Fahrzeug in die Liste aufnehmen
            self.garage_vehicles.append(veh)

            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.2)
            marker.setColor(LColor(0, 0, 1, 1))
            marker.setPos(park.getX(), park.getY(), 0)
            marker.reparentTo(self.render)

            # Suche den Mast des Fahrzeugs (angenommen, er wurde mit dem Namen "mast" angehängt)
            mast = veh.find("**/mast")
            if not mast.isEmpty():
                # Erzeuge einen Textknoten, der die Fahrzeugnummer enthält:
                from panda3d.core import TextNode
                tn = TextNode("vehicle_number")
                tn.setText(str(veh.getPythonTag("vehicle_id")))
                tn.setTextColor(0, 0, 0, 1)  # Schwarz
                tn.setAlign(TextNode.ACenter)
                text_np = mast.attachNewNode(tn)
                # Positioniere den Text relativ zum Mast:
                # Wir nehmen hier den gleichen X- und Y-Versatz wie beim Zylinder (intersection),
                # und setzen den Text in Z-Richtung um z.B. +0.2 Einheiten oberhalb (also intersection.z + 0.2).
                text_np.setPos(intersection.x, intersection.y, intersection.z + 0.2)
                text_np.setScale(0.8)  # Größere Darstellung
                # Optional können mit setHpr weitere Anpassungen vorgenommen werden, sodass der Text optimal lesbar ist.
                text_np.setHpr(0, 0, 0)
            else:
                # Fallback: Falls kein Mast gefunden wird, hänge den Text direkt an das Fahrzeug.
                from panda3d.core import TextNode
                tn = TextNode("vehicle_number")
                tn.setText(str(veh.getPythonTag("vehicle_id")))
                tn.setTextColor(0, 0, 0, 1)
                tn.setAlign(TextNode.ACenter)
                text_np = veh.attachNewNode(tn)
                text_np.setPos(0, 1.2, 1.5)
                text_np.setScale(0.8)
                text_np.setHpr(0, 0, 0)

            # Registriere den Task für das Fahrzeug:
            self.taskMgr.add(partial(self.vehicle_order_task, veh),
                             f"VehicleOrderTask_{veh.getPythonTag('vehicle_id')}")

    def add_cross_on_face(self, corners, color=LColor(1, 1, 1, 1), thickness=1.5):
        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(corners[0])
        ls.drawTo(corners[2])
        ls.moveTo(corners[1])
        ls.drawTo(corners[3])
        return self.render.attachNewNode(ls.create())

    # -----------------------------------
    # FAHRZEUGERSTELLUNG (FFZ20-INTEGRATION)
    # -----------------------------------
    def create_vehicle(self, park_point=None):
        # Erzeuge den übergeordneten Fahrzeug-Knoten
        vehicle_node = self.render.attachNewNode("vehicle")

        # --------------------------
        # Chassis erstellen (1 x 0.5 x 1.2, Farbe Rot)
        # --------------------------
        box_chassis = self.create_box(1, 0.5, 1.2, (1.0, 0.0, 0.0, 1))
        node_chassis = vehicle_node.attachNewNode(box_chassis)
        node_chassis.setTwoSided(True)
        node_chassis.setPos(0, 0, 0)
        edges_chassis = self.create_box_edges(1, 0.5, 1.2, (0, 0, 0, 1))
        edges_chassis.reparentTo(node_chassis)

        # --------------------------
        # Gabel (Fork) erstellen: Zwei Zähne
        # --------------------------
        fork_node = vehicle_node.attachNewNode("fork")
        fork_node.setPos(0, -1.2, 0)
        left_tooth = self.create_box(0.2, 1.2, 0.1, (0.3, 0.3, 0.3, 1))
        node_left = fork_node.attachNewNode(left_tooth)
        node_left.setTwoSided(True)
        right_tooth = self.create_box(0.2, 1.2, 0.1, (0.3, 0.3, 0.3, 1))
        node_right = fork_node.attachNewNode(right_tooth)
        node_right.setTwoSided(True)
        node_right.setPos(0.8, 0, 0)

        # Speichere den Gabel-Knoten als Python-Tag am Fahrzeug
        vehicle_node.setPythonTag("fork_node", fork_node)

        # --------------------------
        # Erzeuge den grünen Referenzmarker (Gabel – grüner Punkt)
        # --------------------------
        ls_new = LineSegs()
        ls_new.setThickness(2.0)
        ls_new.setColor(1, 1, 1, 1)
        left_corner_local = Vec3(0, 0, 0.05)
        right_corner_local = Vec3(1.0, 0, 0.05)
        left_corner_global = fork_node.getPos() + left_corner_local
        right_corner_global = fork_node.getPos() + right_corner_local
        ls_new.moveTo(left_corner_global)
        ls_new.drawTo(right_corner_global)
        vehicle_node.attachNewNode(ls_new.create())
        midpoint = (left_corner_global + right_corner_global) * 0.5
        white_line_vec = right_corner_global - left_corner_global
        white_line_dir = white_line_vec.normalized() if white_line_vec.length() != 0 else Vec3(0, 0, 0)
        candidate = Vec3(-white_line_dir.getY(), white_line_dir.getX(), 0)
        perp_direction = candidate.normalized() if candidate.length() != 0 else Vec3(0, 0, 0)
        green_point_global = midpoint + perp_direction * 0.5

        green_marker = self.create_box(0.05, 0.05, 0.05, (0, 1, 0, 1))
        green_marker_np = vehicle_node.attachNewNode(green_marker)
        green_marker_np.setPos(green_point_global - Vec3(0.025, 0.025, 0.025))
        # Speichere den grünen Marker ebenfalls als Python-Tag
        vehicle_node.setPythonTag("fork_green", green_marker_np)

        # --------------------------
        # Mast und weitere Fahrzeugteile
        # --------------------------
        mast_node = vehicle_node.attachNewNode("mast")
        mast_node.setPos(0, 0.2, 1.2)
        top_bar = self.create_box(1, 0.1, 0.1, (0.2, 0.2, 0.2, 1))
        top_bar_node = mast_node.attachNewNode(top_bar)
        top_bar_node.setPos(0, 0, 0.9)
        bottom_bar = self.create_box(1, 0.1, 0.1, (0.2, 0.2, 0.2, 1))
        bottom_bar_node = mast_node.attachNewNode(bottom_bar)
        bottom_bar_node.setPos(0, 0, 0)
        left_bar = self.create_box(0.1, 0.1, 0.8, (0.2, 0.2, 0.2, 1))
        left_bar_node = mast_node.attachNewNode(left_bar)
        left_bar_node.setPos(0, 0, 0.1)
        right_bar = self.create_box(0.1, 0.1, 0.8, (0.2, 0.2, 0.2, 1))
        right_bar_node = mast_node.attachNewNode(right_bar)
        right_bar_node.setPos(0.9, 0, 0.1)
        mast_node.setTwoSided(True)
        mast_node.setPos(0, 0.2, 1.2)
        self.add_diagonals_to_mast(mast_node)
        intersection = Vec3(0.5, 0.05, 1.0)
        cylinder_node = NodePath(self.create_cylinder(0.1, 0.1, 16, (1, 1, 0, 1)))
        cylinder_node.reparentTo(mast_node)
        cylinder_node.setPos(intersection)
        self.vehicle_cylinder = cylinder_node

        # --------------------------
        # Fahrzeugpositionierung am Parkpunkt
        # --------------------------
        if park_point is None:
            vehicle_node.setPos(intersection.x, intersection.y, 0)
        else:
            vehicle_node.setPos(park_point - vehicle_node.getQuat().xform(intersection))
        return vehicle_node

    def add_diagonals_to_mast(self, mast_node):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(1.0, 0.5, 0.0, 1)
        ls.moveTo(0, 0, 1.0)
        ls.drawTo(1, 0.1, 1.0)
        ls.moveTo(1, 0, 1.0)
        ls.drawTo(0, 0.1, 1.0)
        mast_node.attachNewNode(ls.create())

    def add_lidar_circle(self, parent_node, center, radius):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(0, 1, 0, 1)
        segments = 64
        start_x = center.x + radius * math.cos(0)
        start_y = center.y + radius * math.sin(0)
        ls.moveTo(start_x, start_y, center.z)
        for i in range(1, segments + 1):
            angle = 2 * math.pi * i / segments
            x = center.x + radius * math.cos(angle)
            y = center.y + radius * math.sin(angle)
            ls.drawTo(x, y, center.z)
        parent_node.attachNewNode(ls.create())

    def create_cylinder(self, diameter, height, segments, color):
        fmt = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData("cylinder", fmt, Geom.UHStatic)
        vwriter = GeomVertexWriter(vdata, "vertex")
        nwriter = GeomVertexWriter(vdata, "normal")
        cwriter = GeomVertexWriter(vdata, "color")
        r = diameter / 2.0
        top_z = height / 2.0
        bottom_z = -height / 2.0

        vwriter.addData3f(0, 0, top_z)
        nwriter.addData3f(0, 0, 1)
        cwriter.addData4f(*color)

        for i in range(segments):
            angle = 2 * math.pi * i / segments
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            vwriter.addData3f(x, y, top_z)
            nwriter.addData3f(0, 0, 1)
            cwriter.addData4f(*color)

        vwriter.addData3f(0, 0, bottom_z)
        nwriter.addData3f(0, 0, -1)
        cwriter.addData4f(*color)

        for i in range(segments):
            angle = 2 * math.pi * i / segments
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            vwriter.addData3f(x, y, bottom_z)
            nwriter.addData3f(0, 0, -1)
            cwriter.addData4f(*color)

        top_triangles = GeomTriangles(Geom.UHStatic)
        for i in range(1, segments + 1):
            next_i = 1 if i == segments else i + 1
            top_triangles.addVertices(0, i, next_i)
            top_triangles.closePrimitive()

        bottom_center = segments + 1
        bottom_triangles = GeomTriangles(Geom.UHStatic)
        for i in range(segments):
            curr = segments + 2 + i
            next_i = segments + 2 if i == segments - 1 else curr + 1
            bottom_triangles.addVertices(bottom_center, next_i, curr)
            bottom_triangles.closePrimitive()

        side_triangles = GeomTriangles(Geom.UHStatic)
        for i in range(1, segments + 1):
            next_i = 1 if i == segments else i + 1
            top_i = i
            bottom_i = segments + 1 + i
            bottom_next = segments + 1 + next_i
            side_triangles.addVertices(top_i, next_i, bottom_next)
            side_triangles.closePrimitive()
            side_triangles.addVertices(top_i, bottom_next, bottom_i)
            side_triangles.closePrimitive()

        geom = Geom(vdata)
        geom.addPrimitive(top_triangles)
        geom.addPrimitive(bottom_triangles)
        geom.addPrimitive(side_triangles)
        node = GeomNode("cylinder")
        node.addGeom(geom)
        return node

    def create_box(self, width, depth, height, color):
        fmt = GeomVertexFormat.getV3n3cp()
        vdata = GeomVertexData("box", fmt, Geom.UHStatic)
        vertex = GeomVertexWriter(vdata, "vertex")
        normal = GeomVertexWriter(vdata, "normal")
        col = GeomVertexWriter(vdata, "color")

        for v in [(0, 0, 0), (width, 0, 0), (width, depth, 0), (0, depth, 0)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, -1)
            col.addData4f(*color)
        for v in [(0, 0, height), (width, 0, height), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, 1)
            col.addData4f(*color)
        for v in [(0, 0, 0), (width, 0, 0), (width, 0, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, -1, 0)
            col.addData4f(*color)
        for v in [(0, depth, 0), (width, depth, 0), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 1, 0)
            col.addData4f(*color)
        for v in [(0, 0, 0), (0, depth, 0), (0, depth, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(-1, 0, 0)
            col.addData4f(*color)
        for v in [(width, 0, 0), (width, depth, 0), (width, depth, height), (width, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(1, 0, 0)
            col.addData4f(*color)

        tris = GeomTriangles(Geom.UHStatic)
        for i in range(6):
            base = i * 4
            tris.addVertices(base, base + 1, base + 2)
            tris.closePrimitive()
            tris.addVertices(base, base + 2, base + 3)
            tris.closePrimitive()

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode("box")
        node.addGeom(geom)
        return node

    def create_box_edges(self, width, depth, height, color):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(*color)
        ls.moveTo(0, 0, 0)
        ls.drawTo(width, 0, 0)
        ls.drawTo(width, depth, 0)
        ls.drawTo(0, depth, 0)
        ls.drawTo(0, 0, 0)
        ls.moveTo(0, 0, height)
        ls.drawTo(width, 0, height)
        ls.drawTo(width, depth, height)
        ls.drawTo(0, depth, height)
        ls.drawTo(0, 0, height)
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 0, height)
        ls.moveTo(width, 0, 0)
        ls.drawTo(width, 0, height)
        ls.moveTo(width, depth, 0)
        ls.drawTo(width, depth, height)
        ls.moveTo(0, depth, 0)
        ls.drawTo(0, depth, height)
        return NodePath(ls.create())

    def update_cable(self, task):
        # Verwende die simulative Zeit, die bereits in update_sim_clock hochgezählt wird
        t = self.sim_clock
        new_height = 0.5 + 0.5 * math.sin(t * 2.0)
        self.fork_node.setZ(new_height)
        return Task.cont

    # -----------------------------------
    # FEHLENDE METHODEN: Paketspawning, Würfelerzeugung u.a.
    # -----------------------------------
    def spawn_package_at_station(self, station):
        pos = station.getPos(self.render)
        package = self.erzeuge_wuerfel(pos.x, pos.y, pos.z, LColor(1, 1, 0, 1))
        spawn_time = self.sim_clock
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)

        # Paket eintragen
        self.pickup_packages[station] = (package, spawn_time, timer_np)
        self.last_removed[station] = self.sim_clock

        # Bestimme zufällig eine Abgabestation als Ziel
        if hasattr(self, "abgabe_stations") and self.abgabe_stations:
            target_index = random.randint(1, len(self.abgabe_stations))
        else:
            target_index = 1

        # Erstelle den Auftrag zur Annahmestation
        order = {
            "id": self.next_order_id,
            "status": "Wartend",
            "ziel": f"Abgabestation {target_index}",
            "annahmestation": station.getName(),
            "pickup_station": station,
            "package": package,
            "timer_np": timer_np,
            "spawn_time": spawn_time
        }
        self.orders[order["id"]] = order
        self.orders_queue.append(order)
        self.next_order_id += 1

        print(f"Neuer Auftrag erstellt: {order}")

    def erzeuge_wuerfel(self, x, y, z, color):
        wuerfel = self.loader.loadModel("models/box")
        wuerfel.setScale(1, 1, 1)
        # Hier wird der Höhenoffset innerhalb der Methode gesetzt:
        wuerfel.setPos(x, y, z + 1)
        wuerfel.setColor(color)
        wuerfel.reparentTo(self.render)
        return wuerfel

    def update_package_timers(self, task):
        for station, (package, spawn_time, timer_np) in list(self.pickup_packages.items()):
            # Prüfe, ob der Timer-Knoten noch gültig ist
            if not timer_np.isEmpty():
                elapsed = self.sim_clock - spawn_time
                timer_np.node().setText(f"{elapsed:.1f}s")
            else:
                del self.pickup_packages[station]
        return Task.cont

    def update_order_table(self):
        """
        Aktualisiert die Auftragsübersicht in der Tkinter-Tabelle und zeigt in der
        letzten Spalte den zugewiesenen Fahrzeugnamen (oder "-" falls noch keiner zugeordnet wurde).
        """
        # Lösche alle vorhandenen Einträge in der Auftragsliste.
        for entry in self.order_tree.get_children():
            self.order_tree.delete(entry)

        # Iteriere über alle Aufträge.
        for order_id, order in list(self.orders.items()):
            # Extrahiere aus dem Annahmestationsnamen (z. B. "annahme_station_3") die Stationsnummer.
            pickup_station_str = order.get("annahmestation", "N/A")
            if pickup_station_str != "N/A" and "_" in pickup_station_str:
                pickup_number = pickup_station_str.split("_")[-1]
            else:
                pickup_number = "N/A"

            # Extrahiere aus dem Ziel (z. B. "Abgabestation 5") die Stationsnummer.
            target_station_str = order.get("ziel", "N/A")
            if target_station_str != "N/A" and " " in target_station_str:
                target_number = target_station_str.split()[-1]
            else:
                target_number = "N/A"

            # Zeige in der letzten Spalte den zugewiesenen Fahrzeugnamen an (oder "-" falls noch kein Fahrzeug zugewiesen ist).
            vehicle_display = order.get("vehicle", "-")

            self.order_tree.insert("", tk.END, values=(order_id, pickup_number, target_number, vehicle_display))
        self.order_win.update()

    def check_and_spawn_packages(self, task):
        spawn_delay = 5.0  # 5 Sekunden Verzögerung zwischen Spawns
        for station in self.annahme_stations:
            # Wenn aktuell kein Paket an der Station ist
            if station not in self.pickup_packages:
                last_time = self.last_removed.get(station, self.sim_clock)
                # Prüfe, ob seit der letzten Entnahme mindestens 5 Sekunden vergangen sind
                if (self.sim_clock - last_time) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.cont

    def update_graph_data(self, task):
        avg_dwell = self.total_dwell_time / self.picked_up_count if self.picked_up_count > 0 else 0.0
        ppm = self.delivered_packages / (self.sim_clock / 60) if self.sim_clock > 0 else 0.0
        self.graph_data.append((self.sim_clock, ppm, avg_dwell))
        return Task.again

    def open_graph(self):
        if not self.graph_opened:
            self.init_graph()
            self.fig.canvas.mpl_connect("close_event", self.on_graph_close)
            self.taskMgr.add(self.update_graph_task, "UpdateGraphTask")
            self.graph_opened = True

    def init_graph(self):
        plt.ion()
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(8, 6))
        self.line1, = self.ax1.plot([], [], marker="o", label="Pakete pro Minute")
        self.ax1.set_xlabel("Simulationszeit (s)")
        self.ax1.set_ylabel("Pakete pro Minute")
        self.ax1.set_title("Abgegebene Pakete pro Minute")
        self.ax1.legend()
        self.ax1.grid(True)
        self.line2, = self.ax2.plot([], [], marker="o", color="orange", label="Durchschnittliche Liegedauer (s)")
        self.ax2.set_xlabel("Simulationszeit (s)")
        self.ax2.set_ylabel("Liegedauer (s)")
        self.ax2.set_title("Durchschnittliche Liegedauer")
        self.ax2.legend()
        self.ax2.grid(True)
        plt.show(block=False)

    def update_graph_task(self, task):
        times = [data[0] for data in self.graph_data]
        rates = [data[1] for data in self.graph_data]
        dwell = [data[2] for data in self.graph_data]
        self.line1.set_data(times, rates)
        self.ax1.relim()
        self.ax1.autoscale_view()
        self.line2.set_data(times, dwell)
        self.ax2.relim()
        self.ax2.autoscale_view()
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        plt.pause(0.001)
        return Task.cont

    def on_graph_close(self, event):
        self.graph_opened = False
        self.taskMgr.remove("UpdateGraphTask")

    def show_order_list(self):
        if self.order_win is None:
            self.order_win = tk.Tk()
            self.order_win.title("Auftragsübersicht")
            self.order_win.protocol("WM_DELETE_WINDOW", self.close_order_window)
            # Wir legen hier die Spalten in der gewünschten Reihenfolge an: Auftrags ID, Annahmestation, Ziel, Fahrzeug.
            self.order_tree = ttk.Treeview(
                self.order_win,
                columns=("ID", "Annahmestation", "Ziel", "Fahrzeug"),
                show="headings",
                height=15
            )
            self.order_tree.heading("ID", text="Auftrags ID")
            self.order_tree.heading("Annahmestation", text="Annahmestation")
            self.order_tree.heading("Ziel", text="Ziel")
            self.order_tree.heading("Fahrzeug", text="Fahrzeug")
            self.order_tree.column("ID", width=100, anchor="center")
            self.order_tree.column("Annahmestation", width=150, anchor="center")
            self.order_tree.column("Ziel", width=150, anchor="center")
            self.order_tree.column("Fahrzeug", width=100, anchor="center")
            self.order_tree.pack(fill=tk.BOTH, expand=True)
        else:
            self.order_win.deiconify()
        self.update_order_table()
        self.order_win.lift()


    def update_order_status(self, task):
        # Entferne Aufträge, die den Status "Abgegeben" haben und deren Lieferzeit älter als 2 Sekunden ist.
        for order_id, order in list(self.orders.items()):
            if order.get("status") == "Abgegeben" and self.sim_clock - order.get("delivered_at", 0) >= 2:
                del self.orders[order_id]
        if self.order_win is not None:
            self.update_order_table()
        return Task.cont

    def close_order_window(self):
        if self.order_win is not None:
            self.order_win.withdraw()

    def deliver_first_order(self):
        # Diese Methode wird beim Paket-Zustellen aufgerufen.
        for order_id, order in self.orders.items():
            if order.get("status") == "Wartend":
                order["status"] = "Abgegeben"
                order["delivered_at"] = self.sim_clock
                print(f"Auftrag {order['id']} wurde geliefert.")
                break

    def pickup_package(self, vehicle, station):
        if station in self.pickup_packages:
            package, spawn_time, timer_np = self.pickup_packages.pop(station)
            timer_np.removeNode()
            dwell_time = self.sim_clock - spawn_time
            self.total_dwell_time += dwell_time
            self.picked_up_count += 1

            # Hole die fahrzeugspezifischen Knoten mittels getPythonTag
            fork_node = vehicle.getPythonTag("fork_node")
            fork_green = vehicle.getPythonTag("fork_green")

            # Hole die Position des grünen Markers relativ zum Gabelknoten
            green_point_pos = fork_green.getPos(fork_node)

            # Reparent das Paket zur Gabel des Fahrzeugs und positioniere es entsprechend
            package.wrtReparentTo(fork_node)
            package.setPos(
                green_point_pos.getX() + 0.5,  # Offset in X-Richtung
                green_point_pos.getY() - 0.5,  # Offset in Y-Richtung
                green_point_pos.getZ() + 1  # Z-Offset, sodass das Paket oberhalb liegt
            )

            self.cargos[vehicle] = package
            self.last_removed[station] = self.sim_clock

            if station in self.occupied_pickups:
                self.occupied_pickups.remove(station)

    from direct.task.TaskManagerGlobal import taskMgr  # Sicherstellen, dass taskMgr verfügbar ist

    def drop_cargo(self, vehicle):
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.wrtReparentTo(self.render)
            # Paket wird in Fahrzeug-Nähe abgelegt (kleiner Z-Offset)
            targetPos = vehicle.getPos(self.render) + Vec3(1.2, 1, 1)
            cargo.setPos(targetPos)
            self.delivered_packages += 1

            # Starte einen Task, der nach 3 Sekunden removeCargoTask aufruft,
            # und übergib dabei das cargo als extra Argument:
            taskMgr.doMethodLater(3, self.removeCargoTask, "removeCargoTask", extraArgs=[cargo], appendTask=True)

    def removeCargoTask(self, cargo, task):
        cargo.removeNode()  # Entfernt das Paket aus der Szene
        return task.done

    def removeCargoTask(self, cargo, task):
        cargo.removeNode()  # Entfernt das Paket aus der Szene
        return Task.done

    def select_next_order(self, vehicle):
        # Filtern aller Aufträge mit dem Status "Wartend"
        waiting_orders = [order for order in self.orders.values() if order.get("status") == "Wartend"]
        if not waiting_orders:
            return None

        # Berechne für jeden Auftrag die Liegedauer
        for order in waiting_orders:
            dwell_time = self.sim_clock - order.get("spawn_time", self.sim_clock)
            order["dwell_time"] = dwell_time

        max_dwell = max(order["dwell_time"] for order in waiting_orders)
        tolerance = 0.01  # Zur Berücksichtigung von Rundungsfehlern
        candidates = [order for order in waiting_orders if abs(order["dwell_time"] - max_dwell) < tolerance]
        if not candidates:
            candidates = waiting_orders

        # Verwende das Fahrzeug, das gerade einen Auftrag bekommen soll,
        # um den Abstand der Pickup-Station zu berechnen.
        vehicle_pos = vehicle.getPos(self.render)

        def distance_to_station(order):
            station = order.get("pickup_station")
            if station:
                station_pos = station.getPos(self.render)
                return (station_pos - vehicle_pos).length()
            return float('inf')

        candidates.sort(key=distance_to_station)
        chosen_order = candidates[0]
        # Setze beim Auftrag auch den bearbeitenden Fahrzeugnamen basierend auf unserer benutzerfreundlichen ID:
        chosen_order["vehicle"] = f"Fahrzeug {vehicle.getPythonTag('vehicle_id')}"
        return chosen_order

    def vehicle_order_task(self, vehicle, task):
        dt = ClockObject.getGlobalClock().getDt() * self.speed_factor

        # Bleibt im idle-Zustand, wenn nicht über das Kontrollfenster aktiviert
        if vehicle.getPythonTag("order_state") == "idle":
            return task.cont

        state = vehicle.getPythonTag("order_state")
        current_order = vehicle.getPythonTag("current_order")

        # ------------------ Phase 1: Translate ------------------
        if state == "translate":
            if current_order is None:
                next_order = self.select_next_order(vehicle)
                if next_order is not None:
                    vehicle.setPythonTag("current_order", next_order)
                    next_order["status"] = "In Bearbeitung"
                    print(
                        f"Auftrag {next_order['id']} wird zugewiesen für Fahrzeug {vehicle.getPythonTag('vehicle_id')}.")
                else:
                    print("Kein Auftrag verfügbar – Fallback zum globalen Ziel.")
            current_order = vehicle.getPythonTag("current_order")
            if current_order is not None:
                pickup_station = current_order.get("pickup_station")
                if pickup_station in self.station_blue_dots:
                    blue_target = self.station_blue_dots[pickup_station].getPos(self.render)
                else:
                    blue_target = self.blue_dot.getPos(self.render)
            else:
                blue_target = self.blue_dot.getPos(self.render)

            local_mast = Vec3(0.5, 0.05, 1.0)
            mast_global = vehicle.getPos(self.render) + vehicle.getQuat(self.render).xform(local_mast)
            target_xy = Vec2(blue_target.getX(), blue_target.getY())
            mast_xy = Vec2(mast_global.getX(), mast_global.getY())
            error_vector = target_xy - mast_xy
            threshold = 0.05
            if error_vector.length() > threshold:
                direction = error_vector.normalized()
                move_distance = 1.5 * dt
                current_pos = vehicle.getPos(self.render)
                new_pos = Vec3(current_pos.getX() + direction.getX() * move_distance,
                               current_pos.getY() + direction.getY() * move_distance, 0)
                vehicle.setPos(new_pos)
            else:
                local_offset = vehicle.getQuat(self.render).xform(local_mast)
                exact_pos = Vec3(blue_target.getX() - local_offset.getX(),
                                 blue_target.getY() - local_offset.getY(), 0)
                vehicle.setPos(exact_pos)
                vehicle.setPythonTag("order_state", "rotate")

        # ------------------ Phase 2: Rotate ------------------
        elif state == "rotate":
            desired_angle = math.degrees(math.atan2(self.station_white_direction.getY(),
                                                    self.station_white_direction.getX()))
            desired_angle = (desired_angle + 180) % 360
            current_heading = vehicle.getH() % 360
            angle_diff = ((desired_angle - current_heading + 180) % 360) - 180
            kp_heading = 0.5
            new_heading = current_heading + kp_heading * angle_diff
            vehicle.setH(new_heading)
            if abs(angle_diff) < 1.0:
                vehicle.setPythonTag("order_state", "turn_right")

        # ------------------ Phase 3: Turn Right ------------------
        elif state == "turn_right":
            if vehicle.getPythonTag("turn_right_init") is None:
                vehicle.setPythonTag("turn_right_init", vehicle.getH() % 360)
                vehicle.setPythonTag("turn_right_target", (vehicle.getPythonTag("turn_right_init") + 90) % 360)
                print("Phase 3: Initialisiert für Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      "Start Heading =", vehicle.getPythonTag("turn_right_init"),
                      "Target Heading =", vehicle.getPythonTag("turn_right_target"))
            current_heading = vehicle.getH() % 360
            turn_right_target = vehicle.getPythonTag("turn_right_target")
            angle_diff = ((turn_right_target - current_heading + 180) % 360) - 180
            kp_turn = 0.5
            turn_rate = kp_turn * angle_diff
            new_heading = current_heading + turn_rate * dt
            vehicle.setH(new_heading)
            print("Phase 3: Fahrzeug", vehicle.getPythonTag("vehicle_id"), "- Aktuelles Heading =", current_heading,
                  "Winkelabweichung =", angle_diff,
                  "Neues Heading =", new_heading)
            if abs(angle_diff) < 1.0:
                print("Phase 3: Drehung abgeschlossen für Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      ". Übergang in 'approach'.")
                vehicle.setPythonTag("order_state", "approach")
                vehicle.clearPythonTag("turn_right_init")
                vehicle.clearPythonTag("turn_right_target")

        # ------------------ Phase 4: Approach ------------------
        elif state == "approach":
            if current_order is not None:
                pickup_station = current_order.get("pickup_station")
                target = pickup_station.getPos(self.render) + Vec3(1.2, 1, 0)
            else:
                target = self.station_green_dot.getPos(self.render) + Vec3(1.2, 1, 0)
            current = vehicle.getPos(self.render)
            error_vec = Vec2(target.getX() - current.getX(), target.getY() - current.getY())
            if error_vec.length() > 0.05:
                direction = error_vec.normalized()
                move_distance = 1.5 * dt
                new_pos = Vec3(current.getX() + direction.getX() * move_distance,
                               current.getY() + direction.getY() * move_distance,
                               target.getZ())
                vehicle.setPos(new_pos)
            else:
                vehicle.setPos(target)
                vehicle.setPythonTag("order_state", "pickup")

        # ------------------ Phase 5: Pickup ------------------
        elif state == "pickup":
            fork_node = vehicle.getPythonTag("fork_node")
            current_z = fork_node.getZ()
            target_z = 1.0
            raise_speed = 0.5
            if current_z < target_z:
                fork_node.setZ(min(target_z, current_z + raise_speed * dt))
            else:
                if current_order is None:
                    if self.orders_queue:
                        vehicle.setPythonTag("current_order", self.orders_queue.pop(0))
                    else:
                        print("Keine verfügbaren Aufträge für Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                              ". Überspringe Pickup-Phase.")
                        vehicle.setPythonTag("order_state", "drive_out")
                        return task.cont
                pickup_station = vehicle.getPythonTag("current_order")["pickup_station"]
                self.pickup_package(vehicle, pickup_station)
                vehicle.setPythonTag("package_attached", True)
                vehicle.setPythonTag("drive_out_start", vehicle.getPos(self.render))
                vehicle.setPythonTag("drive_out_target",
                                     vehicle.getPos(self.render) + vehicle.getQuat(self.render).getForward() * 5.0)
                vehicle.setPythonTag("order_state", "drive_out")

        # ------------------ Phase 6: Drive Out ------------------
        elif state == "drive_out":
            fork_node = vehicle.getPythonTag("fork_node")
            current_z = fork_node.getZ()
            if current_z > 0.0:
                lower_speed = 0.5
                fork_node.setZ(max(0.0, current_z - lower_speed * dt))
            current_pos = vehicle.getPos(self.render)
            drive_out_target = vehicle.getPythonTag("drive_out_target")
            diff = drive_out_target - current_pos
            if diff.length() > 0.1:
                move_distance = 0.5 * dt
                step = diff.normalized() * move_distance
                vehicle.setPos(current_pos + step)
            else:
                vehicle.setPythonTag("order_state", "to_delivery")

        # ------------------ Phase 7: To Delivery ------------------
        elif state == "to_delivery":
            delivery_target_str = current_order.get("ziel", "Abgabestation 1")
            try:
                target_index = int(delivery_target_str.split()[-1])
            except ValueError:
                target_index = 1
            if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
                blue_target = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
            else:
                blue_target = self.abgabe_blue_dots[0].getPos(self.render)
            current_pos = vehicle.getPos(self.render)
            diff = blue_target - current_pos
            threshold = 0.5
            move_distance = 1.5 * dt
            if move_distance > diff.length():
                vehicle.setPos(blue_target)
            else:
                vehicle.setPos(current_pos + diff.normalized() * move_distance)
            if (blue_target - vehicle.getPos(self.render)).length() <= threshold:
                print("Phase 7 abgeschlossen: Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      "hat den blauen Punkt der Abgabestation erreicht.")
                vehicle.setPythonTag("order_state", "align_delivery")

        # ------------------ Phase 8: Align Delivery ------------------
        elif state == "align_delivery":
            desired_heading = 90.0
            current_heading = vehicle.getH() % 360
            angle_diff = ((desired_heading - current_heading + 180) % 360) - 180
            print("Phase 8: Align Delivery | Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                  "Current Heading: {:.2f}°, Desired: {:.2f}°, Diff: {:.2f}°".format(
                      current_heading, desired_heading, angle_diff))
            fixed_turn_speed = 90.0
            turn_amount = fixed_turn_speed * dt
            if abs(angle_diff) < 1.0:
                vehicle.setH(desired_heading)
                print("Phase 8 abgeschlossen: Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      "ausgerichtet (Heading = {:.2f}°).".format(desired_heading))
                vehicle.setPythonTag("order_state", "delivery_center")
            else:
                if angle_diff > 0:
                    new_heading = current_heading + turn_amount
                else:
                    new_heading = current_heading - turn_amount
                new_heading %= 360
                vehicle.setH(new_heading)
                print("Phase 8: Rotating - Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      "New Heading set to {:.2f}°".format(new_heading))

        # ------------------ Phase 9: Delivery Approach ------------------
        elif state == "delivery_center":
            delivery_target_str = current_order.get("ziel", "Abgabestation 1")
            try:
                target_index = int(delivery_target_str.split()[-1])
            except ValueError:
                target_index = 1
            if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
                blue_target = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
            else:
                blue_target = self.abgabe_blue_dots[0].getPos(self.render)
            current = vehicle.getPos(self.render)
            target_point = Vec3(blue_target.getX() + 2.3, blue_target.getY() - 0.5, current.getZ())
            print("Phase 9: Zielpunkt der Abgabestation für Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                  "=", target_point)
            error_vec = Vec2(target_point.getX() - current.getX(), target_point.getY() - current.getY())
            tolerance = 0.05
            move_distance = 1.5 * dt
            if error_vec.length() > tolerance:
                direction = error_vec.normalized()
                new_pos = Vec3(current.getX() + direction.getX() * move_distance,
                               current.getY() + direction.getY() * move_distance,
                               current.getZ())
                vehicle.setPos(new_pos)
                print("Phase 9: Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      "bewegt sich von", current, "nach", new_pos)
            else:
                vehicle.setPos(target_point)
                print("Phase 9: Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      "hat den Zielpunkt erreicht.")
                vehicle.setPythonTag("order_state", "drop")
            # Gabel anheben in Phase 9
            fork_node = vehicle.getPythonTag("fork_node")
            current_fork_z = fork_node.getZ()
            if current_fork_z < 1.0:
                new_fork_z = min(1.0, current_fork_z + 0.5 * dt)
                fork_node.setZ(new_fork_z)
                print("Phase 9: Gabel für Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      "wird angehoben (Z =", new_fork_z, ").")

        # ------------------ Phase 10: Dropoff ------------------
        elif state == "drop":
            if vehicle.getPythonTag("package_attached"):
                delivery_target_str = current_order.get("ziel", "Abgabestation 1")
                try:
                    target_index = int(delivery_target_str.split()[-1])
                except ValueError:
                    target_index = 1
                if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
                    blue_target = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
                else:
                    blue_target = self.abgabe_blue_dots[0].getPos(self.render)
                self.drop_cargo(vehicle)
                print("Phase 10: Paket abgesetzt für Fahrzeug", vehicle.getPythonTag("vehicle_id"))
                vehicle.setPythonTag("package_attached", False)
            else:
                fork_node = vehicle.getPythonTag("fork_node")
                current_z = fork_node.getZ()
                if current_z > 0.0:
                    lower_speed = 0.5
                    new_z = max(0.0, current_z - lower_speed * dt)
                    fork_node.setZ(new_z)
                    print("Phase 10: Gabel wird abgesenkt für Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                          ", aktueller Z-Wert =", new_z)
                else:
                    print("Phase 10: Dropoff vollständig abgeschlossen für Fahrzeug",
                          vehicle.getPythonTag("vehicle_id"))
                    vehicle.setPythonTag("order_state", "translate")
                    # Hier ändern wir den Status des Auftrags zu "Abgegeben" statt "Erledigt"
                    current_order["status"] = "Abgegeben"
                    current_order["delivered_at"] = self.sim_clock
                    vehicle.setPythonTag("current_order", None)

        # ------------------ Phase 11: Exit Station and Start Next Order ------------------
        elif state == "phase11":
            if vehicle.getPythonTag("last_delivery_marker") is not None:
                target_point = vehicle.getPythonTag("last_delivery_marker")
            else:
                delivery_target_str = current_order.get("ziel", "Abgabestation 1")
                try:
                    target_index = int(delivery_target_str.split()[-1])
                except ValueError:
                    target_index = 1
                if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
                    target_point = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
                else:
                    target_point = self.abgabe_blue_dots[0].getPos(self.render)
                print("Phase 11: Zielpunkt (blauer Marker) für Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                      "=", target_point)
                current_pos = vehicle.getPos(self.render)
                diff = target_point - current_pos
                if diff.length() > 0.1:
                    move_distance = 0.5 * dt
                    step = diff.normalized() * move_distance
                    vehicle.setPos(current_pos + step)
                    print("Phase 11: Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                          "fährt aus der Station, neue Position =", current_pos + step)
                else:
                    vehicle.setPos(target_point)
                    print("Phase 11: Fahrzeug", vehicle.getPythonTag("vehicle_id"),
                          "hat den blauen Marker erreicht. Nächster Auftrag wird gestartet.")
                    vehicle.setPythonTag("order_state", "next_order")

        return task.cont

    # Neue Methode: Kontrollfenster zur Fahrzeugsteuerung
    def show_vehicle_control(self):
        if hasattr(self, "control_win") and self.control_win.winfo_exists():
            self.control_win.deiconify()
            self.control_win.lift()
            return
        self.control_win = tk.Toplevel()
        self.control_win.title("Fahrzeugsteuerung")
        self.vehicle_state_vars = {}  # Dictionary: Fahrzeug -> StringVar
        row = 0
        for veh in self.garage_vehicles:
            frame = tk.Frame(self.control_win)
            frame.grid(row=row, column=0, sticky="w", padx=5, pady=2)
            # Verwende die benutzerfreundliche Fahrzeug-ID:
            vid = veh.getPythonTag("vehicle_id")
            label = tk.Label(frame, text=f"Fahrzeug {vid}")
            label.pack(side=tk.LEFT)
            state = veh.getPythonTag("order_state")
            if state is None:
                state = "idle"
            var = tk.StringVar(value=state)
            self.vehicle_state_vars[veh] = var
            rb_active = tk.Radiobutton(frame, text="Aufträge bearbeiten", variable=var, value="translate")
            rb_active.pack(side=tk.LEFT)
            rb_standby = tk.Radiobutton(frame, text="Standby", variable=var, value="idle")
            rb_standby.pack(side=tk.LEFT)
            row += 1
        update_btn = tk.Button(self.control_win, text="Übernehmen", command=self.update_vehicle_control)
        update_btn.grid(row=row, column=0, pady=5)

    def update_vehicle_control(self):
        for veh, var in self.vehicle_state_vars.items():
            new_state = var.get()
            veh.setPythonTag("order_state", new_state)
            print(f"Fahrzeug {veh.getPythonTag('vehicle_id')}: Zustand auf {new_state} gesetzt.")


if __name__ == "__main__":
    app = LagerSimulation()
    app.run()
