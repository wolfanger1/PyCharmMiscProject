import random
import math
import matplotlib.pyplot as plt  # Für interaktive Graphen
from panda3d.core import (
    LColor,
    GeomVertexFormat,
    GeomVertexData,
    GeomVertexWriter,
    GeomLines,
    Geom,
    GeomNode,
    ClockObject,
    AmbientLight,
    DirectionalLight,
    Vec3,
    LineSegs,
    TextNode,
    CardMaker,
    RenderModeAttrib
)
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Basis-Simulationsvariablen
        self.sim_clock = 0.0
        self.speed_factor = 1.0

        # Kennzahlen (KPIs)
        self.delivered_packages = 0
        self.max_overall_wait_time = 0.0
        self.total_dwell_time = 0.0
        self.picked_up_count = 0

        # Für das Paketspawning an den Annahmestationen
        self.pickup_packages = {}  # station (NodePath) -> (Paket, Spawnzeit, Timer Node)
        self.last_removed = {}     # station -> Zeitpunkt der letzten Entfernung

        # Für Graph-Daten und Steuerung
        self.graph_data = []       # Tupel: (Sim-Zeit, Pakete pro Minute, Durchschnittliche Liegedauer)
        self.graph_opened = False

        # Ursprung (Koordinatenachsen)
        self.draw_origin()

        # Kameraeinstellungen: Das ganze Feld soll gut sichtbar sein.
        self.cam.setPos(11, -80, 40)
        self.cam.lookAt(11, 30, 0)

        # Licht und Bodenraster erzeugen
        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=70, cell_size=1)

        # Erzeuge die Mauer (das umschließende Rechteck)
        self.create_wall()

        # Erzeuge Annahme-, Abgabe- und Garagenstationen
        self.create_annahme_stations()
        self.create_abgabe_stations()
        self.create_garagen_stations()

        # Setze auf ALLE Annahmestationen Pakete
        for station in self.annahme_stations:
            self.spawn_package_at_station(station)

        # UI: Slider und Info-Anzeige zur Simulationssteuerung
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

        # Zoom-Funktion: Mit dem Mausrad hereinz- bzw. herauszoomen.
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)
        # Graph in extra Fenster per Taste "g" öffnen
        self.accept("g", self.open_graph)

        # Tasks: Aktualisierung der Simulationszeit, Info-Anzeige, Paketspawning, Paket-Timer und Graph-Daten
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
        self.taskMgr.add(self.check_and_spawn_packages, "CheckSpawnPackagesTask")
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimersTask")
        self.taskMgr.doMethodLater(1, self.update_graph_data, "UpdateGraphDataTask")

    def update_simulation_speed(self, speed_factor=None):
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

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

    def zoom_in(self):
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = max(10, current_fov - 5)
        lens.setFov(new_fov)

    def zoom_out(self):
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = min(100, current_fov + 5)
        lens.setFov(new_fov)

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

    def add_cross_on_face(self, corners, color=LColor(1, 1, 1, 1), thickness=1.5):
        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(corners[0])
        ls.drawTo(corners[2])
        ls.moveTo(corners[1])
        ls.drawTo(corners[3])
        return self.render.attachNewNode(ls.create())

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
        station_points = [
            Vec3(0, 5, 0), Vec3(0, 10, 0), Vec3(0, 15, 0),
            Vec3(0, 20, 0), Vec3(0, 25, 0), Vec3(0, 30, 0),
            Vec3(0, 35, 0), Vec3(0, 40, 0), Vec3(0, 45, 0),
            Vec3(0, 50, 0)
        ]
        self.annahme_stations = []
        for i, pt in enumerate(station_points, start=1):
            self.create_annahme_station(pt)
            station_dummy = self.render.attachNewNode(f"annahme_station_{i}")
            station_dummy.setPos(pt)
            self.annahme_stations.append(station_dummy)
            center = pt + Vec3(0.5, 0.5, 0.5)
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)
            green_dot = self.loader.loadModel("models/misc/sphere")
            green_dot.setScale(0.1)
            green_dot.setColor(LColor(0, 1, 0, 1))
            green_dot.setPos(center + Vec3(0, 0, 0.5))
            green_dot.reparentTo(self.render)
            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, 0.5)
            end_line = start_line + Vec3(3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())
            blue_dot = self.loader.loadModel("models/misc/sphere")
            blue_dot.setScale(0.1)
            blue_dot.setColor(LColor(0, 0, 1, 1))
            blue_dot.setPos(end_line)
            blue_dot.reparentTo(self.render)
            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 1.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)
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
        for i, pt in enumerate(station_points, start=1):
            self.create_abgabe_station(pt)
            center = pt + Vec3(0.5, 0.5, 0.5)
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)
            green_dot = self.loader.loadModel("models/misc/sphere")
            green_dot.setScale(0.1)
            green_dot.setColor(LColor(0, 1, 0, 1))
            green_dot.setPos(center + Vec3(0, 0, 0.5))
            green_dot.reparentTo(self.render)
            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, 0.5)
            end_line = start_line + Vec3(-3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())
            blue_dot = self.loader.loadModel("models/misc/sphere")
            blue_dot.setScale(0.1)
            blue_dot.setColor(LColor(0, 0, 1, 1))
            blue_dot.setPos(end_line)
            blue_dot.reparentTo(self.render)
            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x - 0.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)
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
        v4 = pos + Vec3(0, 0, 2)
        v5 = pos + Vec3(1, 0, 2)
        v6 = pos + Vec3(1, 2, 2)
        v7 = pos + Vec3(0, 2, 2)
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
        roof.setPos(pos.x, pos.y, pos.z + 2)
        roof.setColor(LColor(0, 0, 1, 1))
        return roof

    def create_garagen_stations(self):
        station_points = [
            Vec3(3, 58, 0), Vec3(7, 58, 0), Vec3(11, 58, 0),
            Vec3(15, 58, 0), Vec3(19, 58, 0)
        ]
        for i, pt in enumerate(station_points, start=1):
            self.create_garage_station(pt)
            self.add_garage_roof(pt)
            center = pt + Vec3(0.5, 1, 1)
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.2)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)
            tn = TextNode("garage_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 0.5, pt.y - 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

    def erzeuge_wuerfel(self, x, y, z, farbe):
        cube = self.loader.loadModel("models/box")
        cube.setScale(1, 1, 1)
        cube.setPos(x, y, z + 1)
        cube.setColor(farbe)
        cube.reparentTo(self.render)
        return cube

    def check_and_spawn_packages(self, task):
        spawn_delay = self.sim_time(10)
        for station in self.annahme_stations:
            if station not in self.pickup_packages:
                last_time = self.last_removed.get(station, self.sim_clock)
                if (self.sim_clock - last_time) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.cont

    def spawn_package_at_station(self, station):
        pos = station.getPos(self.render)
        package = self.erzeuge_wuerfel(pos.x, pos.y, pos.z, LColor(1, 1, 0, 1))
        spawn_time = self.sim_clock
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)
        self.pickup_packages[station] = (package, spawn_time, timer_np)
        self.last_removed[station] = self.sim_clock

    def update_package_timers(self, task):
        for station, (package, spawn_time, timer_np) in list(self.pickup_packages.items()):
            elapsed = self.sim_clock - spawn_time
            timer_np.node().setText(f"{elapsed:.1f}s")
        return Task.cont

    def sim_time(self, t):
        return t / self.speed_factor if self.speed_factor != 0 else t

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

    def update_graph_data(self, task):
        avg_dwell = self.total_dwell_time / self.picked_up_count if self.picked_up_count > 0 else 0.0
        ppm = self.delivered_packages / (self.sim_clock / 60) if self.sim_clock > 0 else 0
        self.graph_data.append((self.sim_clock, ppm, avg_dwell))
        return Task.again


if __name__ == "__main__":
    app = LagerSimulation()
    app.run()
