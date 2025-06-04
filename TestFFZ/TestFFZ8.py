import random
import math
import matplotlib.pyplot as plt  # Für interaktive Graphen
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData, GeomNode,
    GeomVertexWriter, GeomLines, Geom, Vec3, ClockObject, TextNode, LineSegs,
    CardMaker
)
from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel

# Globaler Clock (wird für die Zeitberechnung genutzt)
globalClock = ClockObject.getGlobalClock()


# =============================================================================
# Klasse: SimulationSurface
# =============================================================================
class SimulationSurface(ShowBase):
    def __init__(self):
        super().__init__()
        # Basisparameter und Statistik
        self.base_speed = 1.5  # Maximalgeschwindigkeit (m/s)
        self.speed_factor = 1.0
        self.sim_clock = 0.0
        self.delivered_packages = 0
        self.max_overall_wait_time = 0.0
        self.total_dwell_time = 0.0
        self.picked_up_count = 0
        self.sim_start_real = globalClock.getFrameTime()

        # Kameraeinstellungen
        self.cam.setPos(0, -60, 30)
        self.cam.lookAt(0, 0, 0)

        # Umgebung, Stationen, UI, Tasks & Graph aufbauen
        self.setup_environment()
        self.setup_stations()
        self.setup_UI()
        self.setup_tasks()
        self.setup_graph()

        # Mausevents (Zoom)
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)

    def setup_environment(self):
        self.erzeuge_licht()
        self.boden = self.erzeuge_bodenraster(center_extent=40, cell_size=1)
        self.draw_coordinate_axes(axis_length=5)

    def setup_stations(self):
        # Erzeuge Pickup-Station (bei x = -9) und Drop-Station (bei x = 9, y = 4)
        self.pickup_station = self.erzeuge_gitterbox(-9, 0, 0, LColor(1, 0, 0, 1))
        self.drop_station = self.erzeuge_gitterbox(9, 4, 0, LColor(0, 1, 0, 1))

        # Zeichne Align-Punkte zur besseren Orientierung an der Pickup-Station
        ls1 = LineSegs()
        ls1.setThickness(3.0)
        ls1.setColor(LColor(1, 1, 1, 1))
        p1 = self.pickup_station.getPos(self.render)
        ls1.moveTo(p1)
        ls1.drawTo(p1 + Vec3(2, 0, 0))
        self.render.attachNewNode(ls1.create())

        # Parallele Linie bei der Pickup-Station (1 Einheit Offset in Y-Richtung)
        ls1_parallel = LineSegs()
        ls1_parallel.setThickness(3.0)
        ls1_parallel.setColor(LColor(1, 1, 1, 1))
        ls1_parallel.moveTo(p1 + Vec3(0, 1, 0))
        ls1_parallel.drawTo(p1 + Vec3(2, 0, 0) + Vec3(0, 1, 0))
        self.render.attachNewNode(ls1_parallel.create())

        # Zeichne Align-Punkte zur besseren Orientierung an der Drop-Station
        ls2 = LineSegs()
        ls2.setThickness(3.0)
        ls2.setColor(LColor(1, 1, 1, 1))
        p2 = self.drop_station.getPos(self.render)
        ls2.moveTo(p2)
        ls2.drawTo(p2 + Vec3(-2, 0, 0))
        self.render.attachNewNode(ls2.create())

        # Parallele Linie bei der Drop-Station (1 Einheit Offset in Y-Richtung)
        ls2_parallel = LineSegs()
        ls2_parallel.setThickness(3.0)
        ls2_parallel.setColor(LColor(1, 1, 1, 1))
        ls2_parallel.moveTo(p2 + Vec3(0, 1, 0))
        ls2_parallel.drawTo(p2 + Vec3(-2, 0, 0) + Vec3(0, 1, 0))
        self.render.attachNewNode(ls2_parallel.create())

        self.pickup_packages = {}
        self.last_removed = {}

    def setup_UI(self):
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

    def setup_tasks(self):
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.doMethodLater(1, self.check_slider_task, "CheckSliderTask")
        self.taskMgr.add(self.check_and_spawn_packages, "CheckSpawnPackages")
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimers")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")

    def setup_graph(self):
        self.graph_opened = False
        self.accept("g", self.open_graph)
        self.graph_data = []

    def update_sim_clock(self, task):
        dt = globalClock.getDt()
        self.sim_clock += dt * self.speed_factor
        return Task.cont

    def check_slider_task(self, task):
        self.update_simulation_speed()
        return Task.cont

    def update_simulation_speed(self, speed_factor=None):
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

    def check_and_spawn_packages(self, task):
        spawn_delay = self.sim_time(1)
        for station in [self.pickup_station, self.drop_station]:
            if station not in self.pickup_packages:
                if (self.sim_clock - self.last_removed.get(station, self.sim_clock)) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.cont

    def spawn_package_at_station(self, station):
        package = self.erzeuge_wuerfel(station.getX(), station.getY(), station.getZ(), LColor(1, 1, 0, 1))
        spawn_time = self.sim_clock
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)
        self.pickup_packages[station] = (package, spawn_time, timer_np)
        self.last_removed[station] = self.sim_clock

    def update_package_timers(self, task):
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_clock - spawn_time
            tn = timer_np.node()
            tn.setText(f"{elapsed:.1f}s")
        return Task.cont

    def update_info_display(self, task):
        current_max = 0
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_clock - spawn_time
            current_max = max(current_max, elapsed)
        self.max_overall_wait_time = max(self.max_overall_wait_time, current_max)
        current_text = f"Liegedauer (aktuell): {current_max:.1f}s" if current_max > 0 else "Kein Paket"
        maximal_text = f"Liegedauer (maximal): {self.max_overall_wait_time:.1f}s"
        avg_val = self.total_dwell_time / self.picked_up_count if self.picked_up_count > 0 else 0.0
        tot = self.sim_clock
        h = int(tot // 3600)
        m = int((tot % 3600) // 60)
        s = tot % 60
        formatted = f"{h}h {m}m {s:.1f}s"
        delivered = self.delivered_packages
        ppm = delivered / (self.sim_clock / 60) if self.sim_clock > 0 else 0
        self.info_label['text'] = (
            f"Laufzeit: {formatted}\nAbgegebene Pakete: {delivered}\n"
            f"Pakete pro Minute: {ppm:.1f}\n{current_text}\n{maximal_text}\n"
            f"Durchschn. Liegedauer: {avg_val:.1f}s"
        )
        return Task.cont

    def sim_time(self, t):
        return t / self.speed_factor if self.speed_factor else t

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

    def erzeuge_licht(self):
        alight = AmbientLight("ambient_light")
        alight.setColor((0.5, 0.5, 0.5, 1))
        self.render.setLight(self.render.attachNewNode(alight))
        dlight = DirectionalLight("directional_light")
        dlight.setColor((1, 1, 1, 1))
        dlightNP = self.render.attachNewNode(dlight)
        dlightNP.setPos(10, -10, 10)
        self.render.setLight(dlightNP)

    def erzeuge_bodenraster(self, center_extent=40, cell_size=1):
        vertex_format = GeomVertexFormat.getV3()
        vdata = GeomVertexData("grid", vertex_format, Geom.UHStatic)
        writer = GeomVertexWriter(vdata, "vertex")
        lines = GeomLines(Geom.UHStatic)
        n = 0
        mi = -center_extent - 0.5
        ma = center_extent + 0.5
        y = mi
        while y <= ma:
            writer.addData3(mi, y, 0)
            writer.addData3(ma, y, 0)
            lines.addVertices(n, n + 1)
            n += 2
            y += cell_size
        x = mi
        while x <= ma:
            writer.addData3(x, mi, 0)
            writer.addData3(x, ma, 0)
            lines.addVertices(n, n + 1)
            n += 2
            x += cell_size
        lines.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(lines)
        node = GeomNode("grid")
        node.addGeom(geom)
        np_grid = self.render.attachNewNode(node)
        np_grid.setColor(0.7, 0.7, 0.7, 1)
        return np_grid

    def erzeuge_gitterbox(self, x, y, z, farbe):
        box = self.loader.loadModel("models/box")
        box.setScale(1, 1, 1)
        box.setPos(x, y, z)
        box.setColor(farbe)
        box.setRenderMode(RenderModeAttrib.MWireframe, 1)
        box.reparentTo(self.render)
        return box

    def erzeuge_wuerfel(self, x, y, z, farbe):
        cube = self.loader.loadModel("models/box")
        cube.setScale(1, 1, 1)
        cube.setPos(x, y, z + 1)
        cube.setColor(farbe)
        cube.reparentTo(self.render)
        return cube

    def draw_coordinate_axes(self, axis_length=5):
        ls = LineSegs()
        ls.setThickness(2)
        ls.setColor(LColor(1, 0, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(axis_length, 0, 0)
        ls.setColor(LColor(0, 1, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, axis_length, 0)
        ls.setColor(LColor(0, 0, 1, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 0, axis_length)
        axes = self.render.attachNewNode(ls.create())
        for axis, pos, color, label in [
            ("X", (axis_length, 0, 0), LColor(1, 0, 0, 1), "X"),
            ("Y", (0, axis_length, 0), LColor(0, 1, 0, 1), "Y"),
            ("Z", (0, 0, axis_length), LColor(0, 0, 1, 1), "Z")
        ]:
            tn = TextNode(f"axis_{axis}")
            tn.setText(label)
            tn.setAlign(TextNode.ACenter)
            np_label = self.render.attachNewNode(tn)
            np_label.setScale(0.5)
            np_label.setPos(pos[0], pos[1], pos[2])
            np_label.setColor(color)
        return axes

    def zoom_in(self):
        lens = self.cam.node().getLens()
        curr = lens.getFov()[0]
        new = max(10, curr - 5)
        lens.setFov(new)
        print(f"Zoom In: FOV von {curr} auf {new}")

    def zoom_out(self):
        lens = self.cam.node().getLens()
        curr = lens.getFov()[0]
        new = min(100, curr + 5)
        lens.setFov(new)
        print(f"Zoom Out: FOV von {curr} auf {new}")


# =============================================================================
# Klasse: VehicleController
# =============================================================================
class VehicleController:
    def __init__(self, surface: SimulationSurface):
        self.surface = surface
        self.vehicles = []  # Liste aller Fahrzeuge
        self.cargos = {}  # Ordnet Fahrzeugen aktuell mitgeführte Pakete zu
        self.current_dropoffs = {}
        self.create_vehicles()

    def create_vehicles(self):
        # Es wird nur ein Fahrzeug erstellt, das an der Pickup-Station startet.
        start_position = self.surface.pickup_station.getPos()
        vehicle = self.surface.loader.loadModel("models/box")
        vehicle.setScale(1, 1, 0.5)
        vehicle.setColor(LColor(0, 0, 1, 1))
        vehicle.setPos(start_position)
        vehicle.reparentTo(self.surface.render)
        vehicle.setPythonTag("role", "pickup_to_dropoff")
        vehicle.setPythonTag("phase", "pickup")  # Fährt auf die Station zu
        vehicle.setPythonTag("speed", 0.0)  # Startet aus dem Stand
        self.add_center_marker(vehicle)
        # Hinzufügen des zusätzlichen Markers: 1 Einheit in Y-Richtung vom Mittelpunkt
        self.add_additional_marker(vehicle)
        self.attach_lidar_sensor(vehicle, offset=Vec3(0.5, 0.5, 0), radius=2.5)
        self.vehicles.append(vehicle)

    def add_center_marker(self, vehicle, scale=0.2):
        marker = self.surface.loader.loadModel("models/misc/sphere")
        marker.setScale(scale)
        marker.setColor(LColor(1, 1, 1, 1))
        marker.reparentTo(vehicle)
        marker.setPos(0, 0, 0.01)

    def add_additional_marker(self, vehicle, scale=0.2):
        marker = self.surface.loader.loadModel("models/misc/sphere")
        marker.setScale(scale)
        marker.setColor(LColor(0, 1, 1, 1))  # Farbe (hier Cyan) – anpassbar
        marker.reparentTo(vehicle)
        # Positioniere den Marker 1 Einheit in Y-Richtung vom Mittelpunkt
        marker.setPos(0, 1, 0.01)

    def attach_lidar_sensor(self, vehicle, offset=Vec3(0.5, 0.5, 0), radius=2.5):
        sensor_np = vehicle.attachNewNode("lidar_sensor")
        sensor_np.setPos(offset)
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(1, 1, 0, 1))
        segments = 64
        ls.moveTo(radius * math.cos(0), radius * math.sin(0), 0)
        for i in range(1, segments + 1):
            angle = (2 * math.pi * i) / segments
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            ls.drawTo(x, y, 0)
        circle_geom = ls.create()
        sensor_np.attachNewNode(circle_geom)

    def get_source_target(self, vehicle):
        role = vehicle.getPythonTag("role")
        if role == "pickup_to_dropoff":
            return self.surface.pickup_station, self.surface.drop_station
        else:
            return self.surface.drop_station, self.surface.pickup_station

    def compute_avoidance_vector(self, vehicle):
        """
        Berechnet einen Abstoßungsvektor basierend auf der Position aller anderen Fahrzeuge.
        Je näher ein anderes Fahrzeug ist, desto stärker wirkt der Abstoßungseffekt.
        """
        avoidance = Vec3(0, 0, 0)
        sensor_center = vehicle.getPos(self.surface.render) + Vec3(0.5, 0.5, 0)
        detection_radius = 2.5  # Sensor-Radius
        for other in self.vehicles:
            if other is vehicle:
                continue
            other_center = other.getPos(self.surface.render)
            diff = sensor_center - other_center
            distance = diff.length()
            if distance < detection_radius and distance > 0:
                avoidance += diff.normalized() * (detection_radius - distance)
        return avoidance

    def move_vehicle_to(self, vehicle, target, on_complete):
        max_speed = 1.5
        accel = 2.5
        decel = 2.5

        def move_task(task):
            dt_real = globalClock.getDt()
            dt = dt_real * self.surface.speed_factor

            pos = vehicle.getPos()
            to_target = target - pos
            distance = to_target.length()

            if distance < 0.05:
                vehicle.setPos(target)
                on_complete()
                vehicle.setPythonTag("speed", 0.0)
                return Task.done

            current_speed = vehicle.getPythonTag("speed")

            # Bei der "deliver"-Phase: Bei Dwell-Delay vor dem Weiterfahren bleiben.
            if vehicle.getPythonTag("phase") == "deliver":
                departure_ready_time = vehicle.getPythonTag("departure_ready_time")
                if self.surface.sim_clock < departure_ready_time:
                    vehicle.setPythonTag("speed", 0.0)
                    return Task.cont

            # Berechne den Abstoßungsvektor basierend auf dem Lidar.
            avoidance_vector = self.compute_avoidance_vector(vehicle)
            avoidance_weight = 1.0  # Feinjustierbar.
            if avoidance_vector.length() > 0:
                desired_direction = (
                            to_target.normalized() + avoidance_vector.normalized() * avoidance_weight).normalized()
            else:
                desired_direction = to_target.normalized()

            # Effektive Bremskraft berechnen
            effective_decel = decel
            if avoidance_vector.length() > 0.1:
                effective_decel *= 1.5
            if distance < 1.0:
                effective_decel *= 2

            # Standard-Beschleunigungs-/Bremslogik
            if distance <= (current_speed ** 2) / (2 * effective_decel):
                new_speed = max(current_speed - effective_decel * dt, 0)
            else:
                new_speed = min(current_speed + accel * dt, max_speed)

            # Prüfung, ob sich das Fahrzeug in einer Station befindet:
            station_region_radius = 2.0
            is_station_phase = False
            if (target - self.surface.pickup_station.getPos()).length() < 0.1 or (
                    target - self.surface.drop_station.getPos()).length() < 0.1:
                if (pos - target).length() < station_region_radius:
                    is_station_phase = True
            if not is_station_phase and vehicle.hasPythonTag("departure_station"):
                departure_station = vehicle.getPythonTag("departure_station")
                if (pos - departure_station.getPos()).length() < station_region_radius:
                    is_station_phase = True

            if is_station_phase:
                new_speed = 0.5

            movement = desired_direction * new_speed * dt
            vehicle.setPos(pos + movement)
            vehicle.setPythonTag("speed", new_speed)
            return Task.cont

        self.surface.taskMgr.add(move_task, f"move_vehicle_{id(vehicle)}_{target}")

    def start_delivery_cycle(self, vehicle, start_pos=None):
        if start_pos is None:
            start_pos = vehicle.getPos()
        vehicle.setPythonTag("job_start", self.surface.sim_clock)
        vehicle.setPythonTag("phase", "pickup")
        source, target = self.get_source_target(vehicle)
        if source not in self.surface.pickup_packages:
            self.surface.spawn_package_at_station(source)
        self.move_vehicle_to(vehicle, source.getPos(), lambda: self.after_pickup(vehicle, source, target))

    def after_pickup(self, vehicle, source, target):
        self.pickup_package(vehicle, source)
        vehicle.setPythonTag("phase", "deliver")
        vehicle.setPythonTag("departure_station", source)
        dwell_delay = 1.0
        vehicle.setPythonTag("departure_ready_time", self.surface.sim_clock + dwell_delay)
        self.move_vehicle_to(vehicle, target.getPos(), lambda: self.after_dropoff(vehicle))

    def after_dropoff(self, vehicle):
        self.drop_cargo(vehicle)
        self.remove_cargo(vehicle)
        self.start_delivery_cycle(vehicle, vehicle.getPos())

    def pickup_package(self, vehicle, source):
        if source in self.surface.pickup_packages:
            package, spawn_time, timer_np = self.surface.pickup_packages.pop(source)
            timer_np.removeNode()
            dwell = self.surface.sim_clock - spawn_time
            self.surface.total_dwell_time += dwell
            self.surface.picked_up_count += 1
            package.wrtReparentTo(vehicle)
            package.setPos(0, 0, 1)
            self.cargos[vehicle] = package
            self.surface.last_removed[source] = self.surface.sim_clock

    def drop_cargo(self, vehicle):
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.wrtReparentTo(self.surface.render)
            _, target = self.get_source_target(vehicle)
            targetPos = target.getPos() + Vec3(0, 0, 1)
            cargo.setPos(targetPos)
            self.surface.delivered_packages += 1

    def remove_cargo(self, vehicle):
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.removeNode()
            self.cargos[vehicle] = None


# =============================================================================
# Hauptprogramm
# =============================================================================
if __name__ == "__main__":
    surface = SimulationSurface()
    vehicle_controller = VehicleController(surface)
    for vehicle in vehicle_controller.vehicles:
        vehicle_controller.start_delivery_cycle(vehicle, vehicle.getPos())
    surface.run()
