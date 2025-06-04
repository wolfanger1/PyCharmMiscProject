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
from panda3d.ai import AIBehaviors   # Importiere AI-Funktionalitäten

from panda3d.core import loadPrcFileData
# Erzwingt ein Fenster mit einer definierten Größe und Titel
loadPrcFileData("", "window-type onscreen")
loadPrcFileData("", "win-size 800 600")
loadPrcFileData("", "window-title Lager Simulation")


# globalClock ist nützlich zur Berechnung von dt
globalClock = ClockObject.getGlobalClock()

class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Basis-Parameter
        self.base_speed = 1.5  # m/s
        self.speed_factor = 1.0
        self.max_steering_rate = 90  # Grad pro Sekunde
        self.acceleration = 2.5  # m/s²
        self.braking_deceleration = -2.5  # m/s² (negativ)

        # Simulationsvariablen und Statistiken
        self.sim_clock = 0.0
        self.delivered_packages = 0
        self.max_overall_wait_time = 0.0
        self.total_dwell_time = 0.0
        self.picked_up_count = 0

        self.sim_start_real = globalClock.getFrameTime()

        # Kameraeinstellungen
        self.cam.setPos(0, -60, 30)
        self.cam.lookAt(0, 0, 0)

        # Szene aufbauen
        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=40, cell_size=1)
        self.draw_coordinate_axes(axis_length=5)

        # Erzeuge 5 Annahme- (rot) und 5 Abgabe-Stationen (grün)
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

        # Zeichne Ausrichtungs-Punkte an den Stationen
        for station in self.annahme_stationen:
            station_pos = station.getPos()
            ls_pickup = LineSegs()
            ls_pickup.setThickness(3.0)
            ls_pickup.setColor(LColor(1, 1, 1, 1))
            ls_pickup.moveTo(station_pos)
            ls_pickup.drawTo(station_pos + Vec3(2, 0, 0))
            self.render.attachNewNode(ls_pickup.create())
        for station in self.annahme_stationen:
            station_pos = station.getPos()
            ls_pickup_offset = LineSegs()
            ls_pickup_offset.setThickness(3.0)
            ls_pickup_offset.setColor(LColor(1, 1, 1, 1))
            ls_pickup_offset.moveTo(station_pos + Vec3(0, 1, 0))
            ls_pickup_offset.drawTo(station_pos + Vec3(2, 1, 0))
            self.render.attachNewNode(ls_pickup_offset.create())
        for station in self.annahme_stationen:
            station_pos = station.getPos()
            ls_align = LineSegs()
            ls_align.setThickness(3.0)
            ls_align.setColor(LColor(1, 1, 0, 1))
            ls_align.moveTo(station_pos)
            ls_align.drawTo(station_pos + Vec3(0, 1, 0.1))
            self.render.attachNewNode(ls_align.create())

        for station in self.abgabe_stationen:
            station_pos = station.getPos()
            ls_dropoff = LineSegs()
            ls_dropoff.setThickness(3.0)
            ls_dropoff.setColor(LColor(1, 1, 1, 1))
            ls_dropoff.moveTo(station_pos)
            ls_dropoff.drawTo(station_pos + Vec3(-2, 0, 0))
            self.render.attachNewNode(ls_dropoff.create())
        for station in self.abgabe_stationen:
            station_pos = station.getPos()
            ls_dropoff_offset = LineSegs()
            ls_dropoff_offset.setThickness(3.0)
            ls_dropoff_offset.setColor(LColor(1, 1, 1, 1))
            ls_dropoff_offset.moveTo(station_pos + Vec3(0, 1, 0))
            ls_dropoff_offset.drawTo(station_pos + Vec3(-2, 1, 0))
            self.render.attachNewNode(ls_dropoff_offset.create())
        for station in self.abgabe_stationen:
            station_pos = station.getPos()
            ls_align_dropoff = LineSegs()
            ls_align_dropoff.setThickness(3.0)
            ls_align_dropoff.setColor(LColor(1, 1, 0, 1))
            ls_align_dropoff.moveTo(station_pos)
            ls_align_dropoff.drawTo(station_pos + Vec3(0, 1, 0.1))
            self.render.attachNewNode(ls_align_dropoff.create())

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
            self.add_center_marker(vehicle)
            self.add_front_marker(vehicle)
            self.add_y_marker(vehicle)
            self.add_alignment_marker(vehicle)
            self.add_offset_circle(vehicle, offset=Vec3(0.5, 0.5, 0.01), circle_radius=1.5)
            self.setup_ai_for_vehicle(vehicle)  # AI-Behaviors initialisieren
            self.vehicles.append(vehicle)

        # Restliche Logik (Pickup/Dropoff etc.)
        self.pickup_packages = {}
        self.last_removed = {}
        for station in self.annahme_stationen:
            self.last_removed[station] = self.sim_clock
        self.occupied_dropoffs = set()
        self.occupied_pickups = set()

        # Slider, Info-Anzeige und Graphen
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
            text="Laufzeit: 0.0 s\nAbgegebene Pakete: 0",
            pos=(1.2, 0, 0.8),
            scale=0.07,
            frameColor=(0, 0, 0, 0)
        )

        self.graph_data = []
        self.taskMgr.doMethodLater(1, self.record_graph_data, "RecordGraphDataTask")
        self.graph_opened = False
        self.accept("g", self.open_graph)
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)

        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.doMethodLater(1, self.check_slider_task, "CheckSliderTask")
        self.taskMgr.add(self.check_and_spawn_packages, "CheckSpawnPackages")
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimers")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
        self.taskMgr.add(self.update_lidar_status, "UpdateLidarStatusTask")

        # Starte den Liefervorgang (Pickup-Phase) gestaffelt
        for i, vehicle in enumerate(self.vehicles):
            self.taskMgr.doMethodLater(i * 0.5,
                                       lambda task, v=vehicle: self.start_delivery_cycle(v, v.getPos()),
                                       f"StartDeliveryCycleTask_{i}")

    def setup_ai_for_vehicle(self, vehicle):
        """
        Initialisiert AIBehaviors für ein Fahrzeug.
        Die Parameter (maxForce, maxSpeed, maxAvoidForce) können je nach Bedarf angepasst werden.
        """
        ai_behaviors = AIBehaviors(vehicle, 10.0, self.base_speed, 1.0)
        vehicle.setPythonTag("ai_behaviors", ai_behaviors)

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

    def open_graph(self):
        if not self.graph_opened:
            self.init_graph()
            self.fig.canvas.mpl_connect("close_event", self.on_graph_close)
            self.taskMgr.add(self.update_graph_task, "UpdateGraphTask")
            self.graph_opened = True

    def on_graph_close(self, event):
        self.graph_opened = False
        self.taskMgr.remove("UpdateGraphTask")

    def init_graph(self):
        plt.ion()
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(8, 6))
        self.line1, = self.ax1.plot([], [], marker="o", label="Pakete pro Minute")
        self.ax1.set_xlabel("Simulationszeit (s)")
        self.ax1.set_ylabel("Pakete pro Minute")
        self.ax1.set_title("Abgegebene Pakete pro Minute")
        self.ax1.legend()
        self.ax1.grid(True)
        self.line2, = self.ax2.plot([], [], marker="o", color="orange",
                                      label="Durchschnittliche Liegedauer (s)")
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

    def record_graph_data(self, task):
        delivered_per_minute = self.delivered_packages / (self.sim_clock / 60.0) if self.sim_clock > 0 else 0
        avg_dwell_time = self.total_dwell_time / self.picked_up_count if self.picked_up_count > 0 else 0
        self.graph_data.append((self.sim_clock, delivered_per_minute, avg_dwell_time))
        return Task.again

    def add_center_marker(self, vehicle, scale=0.2):
        marker = self.loader.loadModel("models/misc/sphere")
        marker.setScale(scale)
        marker.setColor(LColor(0, 1, 0, 1))
        marker.reparentTo(vehicle)
        marker.setPos(0, 0, 0.01)

    def add_front_marker(self, vehicle, scale=0.15):
        marker = self.loader.loadModel("models/misc/sphere")
        marker.setScale(scale)
        marker.setColor(LColor(1, 0, 0, 1))
        marker.reparentTo(vehicle)
        marker.setPos(1.0, 0, 0.01)

    def add_y_marker(self, vehicle, scale=0.15):
        marker = self.loader.loadModel("models/misc/sphere")
        marker.setScale(scale)
        marker.setColor(LColor(0, 1, 0, 1))
        marker.reparentTo(vehicle)
        marker.setPos(0, 1.0, 0.01)

    def add_alignment_marker(self, vehicle, scale=0.15):
        marker = self.loader.loadModel("models/misc/sphere")
        marker.setScale(scale)
        marker.setColor(LColor(1, 1, 0, 1))
        marker.reparentTo(vehicle)
        marker.setPos(0, 1, 0.1)

    def add_offset_circle(self, vehicle, offset=Vec3(0.5, 0.5, 0.01), circle_radius=1.5, num_segments=32):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(0, 1, 0, 1))
        for i in range(num_segments + 1):
            angle = 2 * math.pi * i / num_segments
            x = circle_radius * math.cos(angle)
            y = circle_radius * math.sin(angle)
            if i == 0:
                ls.moveTo(x, y, 0)
            else:
                ls.drawTo(x, y, 0)
        circle_geom = ls.create()
        circle_np = vehicle.attachNewNode(circle_geom)
        circle_np.setPos(offset)
        vehicle.setPythonTag("lidar_circle", circle_np)

    def draw_coordinate_axes(self, axis_length=5):
        ls = LineSegs()
        ls.setThickness(2)
        ls.setColor(1, 0, 0, 1)
        ls.moveTo(0, 0, 0)
        ls.drawTo(axis_length, 0, 0)
        ls.setColor(0, 1, 0, 1)
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, axis_length, 0)
        ls.setColor(0, 0, 1, 1)
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 0, axis_length)
        axes = self.render.attachNewNode(ls.create())
        for axis, pos, color, label in [
            ("X", (axis_length, 0, 0), (1, 0, 0, 1), "X"),
            ("Y", (0, axis_length, 0), (0, 1, 0, 1), "Y"),
            ("Z", (0, 0, axis_length), (0, 0, 1, 1), "Z")
        ]:
            tn = TextNode(f"axis_{axis}")
            tn.setText(label)
            tn.setAlign(TextNode.ACenter)
            np_label = self.render.attachNewNode(tn)
            np_label.setScale(0.5)
            np_label.setPos(pos[0], pos[1], pos[2])
            np_label.setColor(color)
        return axes

    def update_lidar_status(self, task):
        sensor_threshold = 3.0
        for vehicle in self.vehicles:
            pos = vehicle.getPos(self.render)
            total_avoidance = Vec3(0, 0, 0)
            multiplier = 1.0
            phase = vehicle.getPythonTag("phase") if vehicle.hasPythonTag("phase") else "pickup"
            for other in self.vehicles:
                if other is vehicle:
                    continue
                pos_other = other.getPos(self.render)
                diff = pos - pos_other
                d = diff.length()
                if d < sensor_threshold:
                    other_phase = other.getPythonTag("phase") if other.hasPythonTag("phase") else "pickup"
                    if phase == "pickup" and other_phase == "dropoff":
                        candidate = 0.1
                        avoidance_weight = 2.0
                    elif phase == "dropoff" and other_phase == "dropoff":
                        my_dropoff = self.current_dropoffs.get(vehicle)
                        other_dropoff = self.current_dropoffs.get(other)
                        if my_dropoff and other_dropoff:
                            my_distance = (pos - my_dropoff.getPos()).length()
                            other_distance = (pos_other - other_dropoff.getPos()).length()
                            if my_distance > other_distance:
                                candidate = 0.1
                                avoidance_weight = 2.0
                            else:
                                candidate = 1.0
                                avoidance_weight = 1.0
                        else:
                            candidate = 1.0
                            avoidance_weight = 1.0
                    else:
                        candidate = 1.0
                        avoidance_weight = 1.0
                    multiplier = min(multiplier, candidate)
                    if d > 0:
                        total_avoidance += diff.normalized() * (sensor_threshold - d) * avoidance_weight
            static_obstacles = self.annahme_stationen + self.abgabe_stationen + self.anfahrstationen
            for obst in static_obstacles:
                pos_obst = obst.getPos(self.render)
                diff = pos - pos_obst
                d = diff.length()
                if d < sensor_threshold:
                    candidate = 0.1
                    avoidance_weight = 2.0
                    multiplier = min(multiplier, candidate)
                    if d > 0:
                        total_avoidance += diff.normalized() * (sensor_threshold - d) * avoidance_weight
            vehicle.setPythonTag("speed_multiplier", multiplier)
            vehicle.setPythonTag("avoidance", total_avoidance)
            lidar_circle = vehicle.getPythonTag("lidar_circle")
            if lidar_circle:
                if multiplier < 1.0 or total_avoidance.length() > 0.001:
                    lidar_circle.setColor(LColor(1, 0, 0, 1))
                else:
                    lidar_circle.setColor(LColor(0, 1, 0, 1))
        return Task.cont

    def update_sim_clock(self, task):
        dt = globalClock.getDt()
        self.sim_clock += dt * self.speed_factor
        return Task.cont

    def update_info_display(self, task):
        current_max_wait_time = 0
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_clock - spawn_time
            if elapsed > current_max_wait_time:
                current_max_wait_time = elapsed
        self.max_overall_wait_time = max(self.max_overall_wait_time, current_max_wait_time)
        current_wait_text = (
            f"Liegedauer (aktuell): {current_max_wait_time:.1f}s"
            if current_max_wait_time > 0 else "Kein Paket an Annahmestation"
        )
        maximal_wait_text = f"Liegedauer (maximal): {self.max_overall_wait_time:.1f}s"
        avg_dwell_time = self.total_dwell_time / self.picked_up_count if self.picked_up_count > 0 else 0.0
        total_seconds = self.sim_clock
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        formatted_time = f"{hours}h {minutes}m {seconds:.1f}s"
        delivered_per_minute = self.delivered_packages / (self.sim_clock / 60.0) if self.sim_clock > 0 else 0
        self.info_label['text'] = (
            f"Laufzeit: {formatted_time}\n"
            f"Abgegebene Pakete: {self.delivered_packages}\n"
            f"Pakete pro Minute: {delivered_per_minute:.1f}\n"
            f"{current_wait_text}\n"
            f"{maximal_wait_text}\n"
            f"Liegedauer (Durchschnitt): {avg_dwell_time:.1f}s"
        )
        return Task.cont

    def sim_time(self, t):
        return t / self.speed_factor if self.speed_factor else t

    def check_slider_task(self, task):
        self.update_simulation_speed()
        return Task.again

    def update_simulation_speed(self, speed_factor=None):
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label