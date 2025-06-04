import random
import math
import matplotlib.pyplot as plt  # Matplotlib zum Plotten importieren
from panda3d.core import (
    LColor, RenderModeAttrib, GeomVertexFormat, GeomVertexData, GeomNode,
    GeomVertexWriter, GeomLines, Geom, Vec3, ClockObject, TextNode, LineSegs,
    CardMaker
)

# Wir nutzen globalClock für dt.
globalClock = ClockObject.getGlobalClock()

from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Basisgeschwindigkeit & Zeitskalierungsfaktor
        self.base_speed = 1.5  # Maximale Geschwindigkeit in m/s
        self.speed_factor = 1.0

        # Neue Parameter: Beschleunigung und Bremsverzögerung (Simulationseinheiten)
        self.acceleration = 2.5  # m/s²
        self.braking_deceleration = -2.5  # m/s² (negativ)

        # Simulationszeitticker & Statistik
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

        # Erzeuge 5 Annahme- (rot) und 5 Abgabe-Stationen (grün) in einer Linie.
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

        # Zeichne für jede Annahmestation den Align-Punkt (2 m in positive X-Richtung)
        for station in self.annahme_stationen:
            station_pos = station.getPos()
            ls_pickup = LineSegs()
            ls_pickup.setThickness(3.0)
            ls_pickup.setColor(LColor(1, 1, 1, 1))
            ls_pickup.moveTo(station_pos)
            ls_pickup.drawTo(station_pos + Vec3(2, 0, 0))
            self.render.attachNewNode(ls_pickup.create())

        # Zeichne für jede Abgabestation den Align-Punkt (2 m in negative X-Richtung)
        for station in self.abgabe_stationen:
            station_pos = station.getPos()
            ls_dropoff = LineSegs()
            ls_dropoff.setThickness(3.0)
            ls_dropoff.setColor(LColor(1, 1, 1, 1))
            ls_dropoff.moveTo(station_pos)
            ls_dropoff.drawTo(station_pos + Vec3(-2, 0, 0))
            self.render.attachNewNode(ls_dropoff.create())

        # --- Anfahrstationen (Startstationen) für die Fahrzeuge ---
        # Diese Stationen sollen bei Y = 15 nebeneinander mit 4 Meter Abstand in X-Richtung liegen.
        self.anfahrstationen = []
        num_departure = 2  # Zu Beginn nur 2 Fahrzeuge
        spacing_departure = 4.0
        start_x = -spacing_departure * (num_departure - 1) / 2
        for i in range(num_departure):
            pos = Vec3(start_x + i * spacing_departure, 15, 0)
            station = self.erzeuge_gitterbox(pos.getX(), pos.getY(), pos.getZ(), LColor(0.8, 0.8, 0, 1))
            self.anfahrstationen.append(station)

        # Fahrzeuge erstellen, jeweils eines pro Anfahrstation (insgesamt 2 Fahrzeuge)
        self.vehicles = []
        self.cargos = {}  # Fahrzeug -> aktuell transportiertes Paket
        self.current_dropoffs = {}  # Fahrzeug -> zugewiesene Dropoff-Station
        for i, start_station in enumerate(self.anfahrstationen):
            vehicle = self.loader.loadModel("models/box")
            # Änderung: Fahrzeuge doppelt so lang (x-Achse verdoppelt)
            vehicle.setScale(2, 1, 0.5)
            if i % 2 == 0:
                vehicle.setColor(LColor(0, 0, 1, 1))
            else:
                vehicle.setColor(LColor(0, 0, 0.8, 1))
            vehicle.setPos(start_station.getPos())
            vehicle.reparentTo(self.render)
            # Initialisiere die aktuelle Geschwindigkeit
            vehicle.setPythonTag("current_speed", 0.0)
            # Beim Start wird die Phase "pickup" gesetzt
            vehicle.setPythonTag("phase", "pickup")
            self.add_center_marker(vehicle)
            self.add_offset_circle(vehicle, offset=Vec3(0.5, 0.5, 0.01), circle_radius=1.5)
            self.vehicles.append(vehicle)

        # Reste der Pick-up-/Drop-off-Logik
        self.pickup_packages = {}
        self.last_removed = {}
        for station in self.annahme_stationen:
            self.last_removed[station] = self.sim_clock
        self.occupied_dropoffs = set()
        self.occupied_pickups = set()

        # Slider und Info-Anzeige
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

        # Erfassung von Daten für Graphen (einmal pro Simulationssekunde)
        self.graph_data = []
        self.taskMgr.doMethodLater(1, self.record_graph_data, "RecordGraphDataTask")

        # Graphen öffnen per Taste "G" (nach Schließen wieder möglich)
        self.graph_opened = False
        self.accept("g", self.open_graph)

        # Zoom-Funktionalität: Mit Mausrad hereinz- bzw. herauszoomen
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)

        # Aufgaben
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.doMethodLater(1, self.check_slider_task, "CheckSliderTask")
        self.taskMgr.add(self.check_and_spawn_packages, "CheckSpawnPackages")
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimers")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
        self.taskMgr.add(self.update_lidar_status, "UpdateLidarStatusTask")

        # Liefervorgang starten (Pickup-Phase) für jedes Fahrzeug mit gestaggertem Start
        for i, vehicle in enumerate(self.vehicles):
            self.taskMgr.doMethodLater(i * 0.5,
                                       lambda task, v=vehicle: self.start_delivery_cycle(v, v.getPos()),
                                       f"StartDeliveryCycleTask_{i}"
                                       )

    def zoom_in(self):
        # Hereinzoomen: Field-of-View (FOV) verkleinern (nicht unter 10°)
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = max(10, current_fov - 5)
        lens.setFov(new_fov)
        print(f"Zoom In: FOV von {current_fov} auf {new_fov}")

    def zoom_out(self):
        # Herauszoomen: FOV vergrößern (nicht über 100°)
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
        self.line2, = self.ax2.plot([], [], marker="o", color="orange", label="Durchschnittliche Liegedauer (s)")
        self.ax2.set_xlabel("Simulationszeit (s)")
        self.ax2.set_ylabel("Liegedauer (s)")
        self.ax2.setTitle("Durchschnittliche Liegedauer")
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
        marker.setColor(LColor(1, 1, 1, 1))
        marker.reparentTo(vehicle)
        marker.setPos(0, 0, 0.01)

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
            # Standardmäßig volle Geschwindigkeit
            multiplier = 1.0
            phase = vehicle.getPythonTag("phase") if vehicle.hasPythonTag("phase") else "pickup"
            # Dynamische Hindernisse: Andere Fahrzeuge
            for other in self.vehicles:
                if other is vehicle:
                    continue
                pos_other = other.getPos(self.render)
                diff = pos - pos_other
                d = diff.length()
                if d < sensor_threshold:
                    other_phase = other.getPythonTag("phase") if other.hasPythonTag("phase") else "pickup"
                    # Priorität: Falls ein Fahrzeug in Pickup einem in Dropoff gegenübersteht
                    if phase == "pickup" and other_phase == "dropoff":
                        candidate = 0.1
                        avoidance_weight = 2.0
                    # Falls beide Fahrzeuge in Dropoff sind, entscheidet der Abstand zur Dropoff-Station
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

            # Statische Hindernisse (Annahme-, Abgabe- und Anfahrstationen)
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
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

    def check_and_spawn_packages(self, task):
        spawn_delay = self.sim_time(1)
        for station in self.annahme_stationen:
            if station not in self.pickup_packages:
                if (self.sim_clock - self.last_removed.get(station, self.sim_clock)) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.cont

    def spawn_package_at_station(self, station):
        package = self.erzeuge_wuerfel(
            station.getX(), station.getY(), station.getZ(), LColor(1, 1, 0, 1)
        )
        spawn_time = self.sim_clock
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)
        self.pickup_packages[station] = (package, spawn_time, timer_np)

    def update_package_timers(self, task):
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_clock - spawn_time
            tn = timer_np.node()
            tn.setText(f"{elapsed:.1f}s")
        return Task.cont

    def move_vehicle_to(self, vehicle, target, on_complete):
        def move_task(task):
            dt = globalClock.getDt()
            # Nutze sim_dt als simulierte Zeit (dt * Speed Factor)
            sim_dt = dt * self.speed_factor
            current_pos = vehicle.getPos()
            to_target = target - current_pos
            distance = to_target.length()

            # Geschwindigkeitsbegrenzung anhand des aktuellen avoidance multipliers
            multiplier = vehicle.getPythonTag("speed_multiplier") if vehicle.hasPythonTag("speed_multiplier") else 1.0
            effective_max_speed = self.base_speed * multiplier  # in m/s im Simulationszeitmaßstab

            current_speed = vehicle.getPythonTag("current_speed") if vehicle.hasPythonTag("current_speed") else 0.0

            # Berechne den notwendigen Bremsweg: v² / (2 * |a|)
            braking_distance = (current_speed * current_speed) / (
                        2 * abs(self.braking_deceleration)) if current_speed > 0 else 0

            if distance <= braking_distance:
                # Bremsvorgang
                new_speed = current_speed + self.braking_deceleration * sim_dt
                new_speed = max(new_speed, 0.0)
            else:
                # Beschleunigen bis zur maximalen effektiven Geschwindigkeit
                new_speed = current_speed + self.acceleration * sim_dt
                new_speed = min(new_speed, effective_max_speed)

            step_distance = new_speed * sim_dt

            if distance <= step_distance:
                vehicle.setPos(target)
                vehicle.setPythonTag("current_speed", 0.0)
                on_complete()
                return Task.done

            avoidance = vehicle.getPythonTag("avoidance") if vehicle.hasPythonTag("avoidance") else Vec3(0, 0, 0)
            if avoidance.length() > 0.001:
                combined = to_target.normalized() + avoidance.normalized() * 0.5
                if combined.length() > 0.001:
                    combined.normalize()
                else:
                    combined = to_target.normalized()
                new_direction = combined
            else:
                new_direction = to_target.normalized()

            new_pos = current_pos + new_direction * step_distance
            vehicle.setPos(new_pos)
            vehicle.setPythonTag("current_speed", new_speed)
            return Task.cont

        self.taskMgr.add(move_task, f"move_vehicle_{id(vehicle)}_{target}")

    def start_delivery_cycle(self, vehicle, start_pos=None):
        if start_pos is None:
            start_pos = vehicle.getPos()
        # Beginn eines neuen Auftrags: Phase "pickup" und Speichern des job_start-Zeitpunkts
        vehicle.setPythonTag("job_start", self.sim_clock)
        vehicle.setPythonTag("phase", "pickup")
        if not self.pickup_packages:
            def wait_task(task):
                if self.pickup_packages:
                    self.start_delivery_cycle(vehicle, vehicle.getPos())
                    return Task.done
                return Task.cont

            self.taskMgr.add(wait_task, f"WaitPackage_{id(vehicle)}")
            return
        current_time = self.sim_clock
        # Verfügbare Pickup-Stationen, die momentan nicht belegt sind
        available_pickups = [s for s in self.pickup_packages.keys() if s not in self.occupied_pickups]
        if not available_pickups:
            def wait_for_pickup(task):
                if any(s not in self.occupied_pickups for s in self.pickup_packages.keys()):
                    self.start_delivery_cycle(vehicle, vehicle.getPos())
                    return Task.done
                return Task.cont

            self.taskMgr.add(wait_for_pickup, f"WaitPickup_{id(vehicle)}")
            return

        # Kombiniertes Ranking: Wartezeit minus ein Anteil an der Entfernung
        distance_weight = 0.5  # Anpassbar
        pickup_station = max(available_pickups, key=lambda s: (current_time - self.pickup_packages[s][1]) - distance_weight * (s.getPos() - vehicle.getPos()).length())
        self.occupied_pickups.add(pickup_station)
        pickup_align = pickup_station.getPos() + Vec3(2, 0, 0)
        self.move_vehicle_to(vehicle, pickup_align,
                             lambda: self.move_vehicle_to(vehicle, pickup_station.getPos(),
                                                          lambda: self.after_pickup(vehicle, pickup_station)
                                                          )
                             )

    def after_pickup(self, vehicle, pickup_station):
        self.pickup_package(vehicle, pickup_station)
        # Nach erfolgreichem Pickup Phase auf "dropoff" setzen
        vehicle.setPythonTag("phase", "dropoff")
        self.depart_from_pickup(vehicle, pickup_station,
                                lambda: self.start_dropoff_phase(vehicle)
                                )

    def depart_from_pickup(self, vehicle, pickup_station, callback):
        departure_align = pickup_station.getPos() + Vec3(2, 0, 0)
        departure_target = pickup_station.getPos() + Vec3(4, 0, 0)
        self.move_vehicle_to(vehicle, departure_align,
                             lambda: self.move_vehicle_to(vehicle, departure_target, callback)
                             )

    def start_dropoff_phase(self, vehicle):
        available_dropoffs = [ds for ds in self.abgabe_stationen if ds not in self.occupied_dropoffs]
        if not available_dropoffs:
            self.start_dropoff_phase(vehicle)
            return
        dropoff_station = random.choice(available_dropoffs)
        self.occupied_dropoffs.add(dropoff_station)
        self.current_dropoffs[vehicle] = dropoff_station
        dropoff_align = dropoff_station.getPos() + Vec3(-2, 0, 0)
        self.move_vehicle_to(vehicle, dropoff_align,
                             lambda: self.move_vehicle_to(vehicle, dropoff_station.getPos(),
                                                          lambda: self.after_dropoff(vehicle)
                                                          )
                             )

    def after_dropoff(self, vehicle):
        dropoff_station = self.current_dropoffs.get(vehicle)
        self.drop_cargo(vehicle)
        self.remove_cargo(vehicle, remove_dropoff=True)
        if dropoff_station is not None:
            departure_align = dropoff_station.getPos() + Vec3(-2, 0, 0)
            departure_target = dropoff_station.getPos() + Vec3(-4, 0, 0)
            self.move_vehicle_to(vehicle, departure_align,
                                 lambda: self.move_vehicle_to(vehicle, departure_target,
                                                              lambda: self.start_delivery_cycle(vehicle, departure_target)
                                                              )
                                 )
        else:
            self.start_delivery_cycle(vehicle, vehicle.getPos())

    def pickup_package(self, vehicle, station):
        if station in self.pickup_packages:
            package, spawn_time, timer_np = self.pickup_packages.pop(station)
            timer_np.removeNode()
            dwell_time = self.sim_clock - spawn_time
            self.total_dwell_time += dwell_time
            self.picked_up_count += 1
            package.wrtReparentTo(vehicle)
            package.setPos(0, 0, 1)
            self.cargos[vehicle] = package
            self.last_removed[station] = self.sim_clock
            if station in self.occupied_pickups:
                self.occupied_pickups.remove(station)

    def drop_cargo(self, vehicle):
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.wrtReparentTo(self.render)
            targetPos = self.current_dropoffs[vehicle].getPos() + Vec3(0, 0, 1)
            cargo.setPos(targetPos)
            self.delivered_packages += 1

    def remove_cargo(self, vehicle, remove_dropoff=True):
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.removeNode()
            self.cargos[vehicle] = None
        if remove_dropoff:
            dropoff_station = self.current_dropoffs.get(vehicle)
            if dropoff_station in self.occupied_dropoffs:
                self.occupied_dropoffs.remove(dropoff_station)
            if vehicle in self.current_dropoffs:
                del self.current_dropoffs[vehicle]

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

    def erzeuge_gitterbox(self, x, y, z, farbe):
        gitterbox = self.loader.loadModel("models/box")
        gitterbox.setScale(1, 1, 1)
        gitterbox.setPos(x, y, z)
        gitterbox.setColor(farbe)
        gitterbox.setRenderMode(RenderModeAttrib.MWireframe, 1)
        gitterbox.reparentTo(self.render)
        return gitterbox

    def erzeuge_wuerfel(self, x, y, z, farbe):
        wuerfel = self.loader.loadModel("models/box")
        wuerfel.setScale(1, 1, 1)
        wuerfel.setPos(x, y, z + 1)
        wuerfel.setColor(farbe)
        wuerfel.reparentTo(self.render)
        return wuerfel

    def erzeuge_licht(self):
        alight = AmbientLight("ambient_light")
        alight.setColor((0.5, 0.5, 0.5, 1))
        self.render.setLight(self.render.attachNewNode(alight))
        dlight = DirectionalLight("directional_light")
        dlight.setColor((1, 1, 1, 1))
        dlightNP = self.render.attachNewNode(dlight)
        dlightNP.setPos(10, -10, 10)
        self.render.setLight(dlightNP)


app = LagerSimulation()
app.run()

#Hier ist in die Fahrlogik die sequenzielle abarbeitung inkludiert. Nicht nur der Zeitfaktor, auc hder Weg spielt eine Rolle
