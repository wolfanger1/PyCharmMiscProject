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
    LineSegs,
    Vec3,
    NodePath
)
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel
import math
import random  # für zufällige Hindernisse


class SimpleSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Initialwerte
        self.sim_clock = 0.0
        self.speed_factor = 1.0
        self.current_speed = 1.5  # Standardgeschwindigkeit in m/s

        # Kameraeinstellungen (Fahrtrichtung: entlang der Y-Achse)
        self.cam.setPos(0, -30, 10)
        self.cam.lookAt(0, 0, 0)

        # Licht und Raster erstellen
        self.setup_light()
        self.create_grid(center_extent=10, cell_size=0.1)

        # Hindernisse erzeugen und speichern
        self.create_random_obstacles(obstacle_count=10)

        # Fahrzeug erstellen (Chassis, Gabel, Mast, etc.)
        self.vehicle = self.create_vehicle()

        # Regler für die Simulationsgeschwindigkeit
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

        # Laufzeitanzeige
        self.info_label = DirectLabel(
            text="Laufzeit: 0.0s",
            pos=(1.2, 0, 0.8),
            scale=0.07,
            frameColor=(0, 0, 0, 0)
        )

        # Zoom via Mausrad
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)

        # Update-Tasks
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
        # Der Fahrzeug-Task enthält nun das Bremsen und das Ausweichen.
        self.taskMgr.add(self.update_vehicle, "UpdateVehicleTask")
        # Optional: Task für Gabel-Animation
        # self.taskMgr.add(self.update_cable, "UpdateCableTask")

    def update_sim_clock(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.sim_clock += dt * self.speed_factor
        return Task.cont

    def update_info_display(self, task):
        total_seconds = self.sim_clock
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        formatted_time = f"{hours}h {minutes}m {seconds:.1f}s"
        self.info_label['text'] = f"Laufzeit: {formatted_time}"
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
        dt = ClockObject.getGlobalClock().getDt()
        pos = self.vehicle.getPos()
        current_heading = self.vehicle.getH()

        # Berechne die aktuelle Vorwärtsrichtung (in der XY-Ebene)
        forward = self.vehicle.getQuat().getForward()
        forward.setZ(0)
        if forward.length() != 0:
            forward.normalize()

        # ------------ Hindernisvermeidung mittels "Lidar" -------------
        avoidance_vector = Vec3(0, 0, 0)
        detection_radius = 5.0  # Erfassungsreichweite des Lidar-Sensors
        avoidance_strength = 2.0  # Multiplikator für einen stärkeren repulsiven Einfluss

        for obs in self.obstacles:
            obs_pos = obs.getPos()
            delta = obs_pos - pos
            delta.setZ(0)
            distance = delta.length()
            # Nur Hindernisse berücksichtigen, die vor dem Fahrzeug liegen
            if distance < detection_radius and delta.dot(forward) > 0:
                weight = (detection_radius - distance) / detection_radius
                repulsion = (pos - obs_pos).normalized() * weight * avoidance_strength
                avoidance_vector += repulsion

        # Kombination: Standardvorwärts plus repulsive Komponente
        desired_direction = forward + avoidance_vector
        # Falls sich beide Vektoren nahezu aufheben (z. B. wenn ein Hindernis direkt vor dem Fahrzeug liegt),
        # wähle eine zusätzliche Ausweichrichtung (z. B. ein Schwenken nach rechts).
        if desired_direction.length() < 0.001:
            desired_direction = forward + Vec3(0.5, 0, 0)
        desired_direction.normalize()

        # Bestimme den gewünschten Heading (0° entspricht der Y-Achse)
        desired_heading = math.degrees(math.atan2(desired_direction.getX(), desired_direction.getY()))

        # Berechne den kleinsten Drehwinkel (normalisiert zwischen -180° und 180°)
        angle_diff = (desired_heading - current_heading + 180) % 360 - 180
        turn_rate = 90.0  # Maximale Drehgeschwindigkeit (Grad/s)
        max_turn = turn_rate * dt
        angle_change = max(-max_turn, min(max_turn, angle_diff))
        new_heading = current_heading + angle_change
        self.vehicle.setH(new_heading)

        # Neuberechnung der Vorwärtsrichtung nach Drehung
        new_forward = self.vehicle.getQuat().getForward()
        new_forward.setZ(0)
        if new_forward.length() != 0:
            new_forward.normalize()

        # ------------ Brems-Logik ------------
        default_speed = 1.5    # Normale Fahrgeschwindigkeit (m/s)
        brake_distance = 2.0   # Ab diesem Abstand wird abgebremst
        min_distance = float('inf')
        for obs in self.obstacles:
            obs_pos = obs.getPos()
            delta = obs_pos - pos
            delta.setZ(0)
            # Berücksichtige nur Hindernisse vor dem Fahrzeug (im Bereich der aktuellen Fahrtrichtung)
            if delta.dot(new_forward) > 0:
                d = delta.length()
                if d < min_distance:
                    min_distance = d
        if min_distance == float('inf'):
            target_speed = default_speed
        elif min_distance < brake_distance:
            target_speed = default_speed * (min_distance / brake_distance)
        else:
            target_speed = default_speed

        # Sanfte Geschwindigkeitsanpassung (Beschleunigen bzw. Bremsen)
        acc_rate = 2.0  # m/s²
        if self.current_speed < target_speed:
            self.current_speed = min(self.current_speed + acc_rate * dt, target_speed)
        elif self.current_speed > target_speed:
            self.current_speed = max(self.current_speed - acc_rate * dt, target_speed)

        # Aktualisiere die Fahrzeugposition
        new_pos = pos + new_forward * self.current_speed * dt
        self.vehicle.setPos(new_pos)
        return Task.cont

    def create_random_obstacles(self, obstacle_count=10):
        """
        Erzeugt zufällig platzierte Hindernisse im vorderen Bereich der Simulation.
        Die erstellten Hindernisse werden in self.obstacles gespeichert, sodass der "Lidar"
        diese erkennen kann.
        """
        self.obstacles = []
        for i in range(obstacle_count):
            # Zufällige Größe zwischen 0.5 und 1.5 (Breite, Tiefe, Höhe)
            width = random.uniform(0.5, 1.5)
            depth = random.uniform(0.5, 1.5)
            height = random.uniform(0.5, 1.5)
            # Zufällige Position: X zwischen -8 und 8, Y zwischen 10 und 50
            x_pos = random.uniform(-8, 8)
            y_pos = random.uniform(10, 50)
            # Erstelle eine Box als Hindernis (dunkles Grau)
            obstacle = self.create_box(width, depth, height, (0.3, 0.3, 0.3, 1))
            obstacle_np = self.render.attachNewNode(obstacle)
            obstacle_np.setPos(x_pos, y_pos, 0)
            self.obstacles.append(obstacle_np)
        print(f"{obstacle_count} zufällige Hindernisse erzeugt.")

    def create_grid(self, center_extent=40, cell_size=1):
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
            lines.closePrimitive()
            n_vertices += 2
            y += cell_size

        x = min_line
        while x <= max_line:
            writer.addData3f(x, min_line, 0)
            writer.addData3f(x, max_line, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            lines.closePrimitive()
            n_vertices += 2
            x += cell_size

        geom = Geom(vdata)
        geom.addPrimitive(lines)
        node = GeomNode("grid")
        node.addGeom(geom)
        grid_np = self.render.attachNewNode(node)
        grid_np.setColor(0.7, 0.7, 0.7, 1)
        return grid_np

    def setup_light(self):
        ambient_light = AmbientLight("ambient_light")
        ambient_light.setColor((0.5, 0.5, 0.5, 1))
        ambient_np = self.render.attachNewNode(ambient_light)
        self.render.setLight(ambient_np)

        directional_light = DirectionalLight("directional_light")
        directional_light.setColor((1, 1, 1, 1))
        directional_np = self.render.attachNewNode(directional_light)
        directional_np.setPos(10, -10, 10)
        self.render.setLight(directional_np)

    def create_vehicle(self):
        vehicle_node = self.render.attachNewNode("vehicle")

        # Fahrmodul (Chassis): 1 x 0.5 x 1.2 (Rot)
        box_chassis = self.create_box(1, 0.5, 1.2, (1.0, 0.0, 0.0, 1))
        node_chassis = vehicle_node.attachNewNode(box_chassis)
        node_chassis.setTwoSided(True)
        node_chassis.setPos(0, 0, 0)

        # Schwarze Kanten zum Fahrmodul
        edges_chassis = self.create_box_edges(1, 0.5, 1.2, (0, 0, 0, 1))
        edges_chassis.reparentTo(node_chassis)

        # Gabelmodul (Fork): Zwei Zähne (je 0.2 x 1.2 x 0.1)
        fork_node = vehicle_node.attachNewNode("fork")
        fork_node.setPos(0, -1.2, 0)
        left_tooth = self.create_box(0.2, 1.2, 0.1, (0.3, 0.3, 0.3, 1))
        node_left = fork_node.attachNewNode(left_tooth)
        node_left.setTwoSided(True)
        node_left.setPos(0, 0, 0)
        right_tooth = self.create_box(0.2, 1.2, 0.1, (0.3, 0.3, 0.3, 1))
        node_right = fork_node.attachNewNode(right_tooth)
        node_right.setTwoSided(True)
        node_right.setPos(0.8, 0, 0)
        self.fork_node = fork_node

        # Zeichne Linie, die die äußersten Ecken des hinteren Endes der Zähne verbindet
        left_corner_local = Vec3(0, 0, 0.05)
        right_corner_local = Vec3(1.0, 0, 0.05)
        left_corner_global = fork_node.getPos() + left_corner_local
        right_corner_global = fork_node.getPos() + right_corner_local

        ls_new = LineSegs()
        ls_new.setThickness(2.0)
        ls_new.setColor(1, 1, 1, 1)
        ls_new.moveTo(left_corner_global)
        ls_new.drawTo(right_corner_global)
        vehicle_node.attachNewNode(ls_new.create())

        # Zusätzliche Linie: von der Mitte senkrecht in Fahrtrichtung
        midpoint = (left_corner_global + right_corner_global) * 0.5
        white_line_vec = right_corner_global - left_corner_global
        if white_line_vec.length() != 0:
            white_line_dir = white_line_vec.normalized()
        else:
            white_line_dir = Vec3(0, 0, 0)
        candidate = Vec3(-white_line_dir.getY(), white_line_dir.getX(), 0)
        vehicle_pos = vehicle_node.getPos()
        if candidate.dot(vehicle_pos - midpoint) < 0:
            candidate = -candidate
        if candidate.length() != 0:
            perp_direction = candidate.normalized()
        else:
            perp_direction = Vec3(0, 0, 0)
        line_length = 1.0
        line_end = midpoint + perp_direction * line_length

        ls_mid = LineSegs()
        ls_mid.setThickness(2.0)
        ls_mid.setColor(1, 1, 1, 1)
        ls_mid.moveTo(midpoint)
        ls_mid.drawTo(line_end)
        vehicle_node.attachNewNode(ls_mid.create())

        # Grüner Marker 0.5 m vom Schnittpunkt entlang der senkrechten Richtung
        green_point_global = midpoint + perp_direction * 0.5
        green_marker = self.create_box(0.05, 0.05, 0.05, (0, 1, 0, 1))
        green_marker_np = vehicle_node.attachNewNode(green_marker)
        green_marker_np.setPos(green_point_global - Vec3(0.05 / 2, 0.05 / 2, 0.05 / 2))

        # Restlicher Fahrzeugaufbau (Mast, Diagonalen, etc.)
        mast_node = vehicle_node.attachNewNode("mast")
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

        lidar_center = Vec3(intersection.x, intersection.y, -1)
        self.add_lidar_circle(mast_node, lidar_center, 2)

        # Positioniere den Fahrzeugknoten so, dass dessen X- und Y-Koordinaten dem Schnittpunkt entsprechen
        vehicle_node.setPos(intersection.x, intersection.y, 0)
        # Anfangsrichtung: entlang der Y-Achse
        vehicle_node.setH(0)

        return vehicle_node

    def add_diagonals_to_mast(self, mast_node):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(1.0, 0.5, 0.0, 1)  # Orange
        ls.moveTo(0, 0, 1.0)
        ls.drawTo(1, 0.1, 1.0)
        ls.moveTo(1, 0, 1.0)
        ls.drawTo(0, 0.1, 1.0)
        mast_node.attachNewNode(ls.create())

    def add_lidar_circle(self, parent_node, center, radius):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(0, 1, 0, 1)  # Grün
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

        # Top center
        vwriter.addData3f(0, 0, top_z)
        nwriter.addData3f(0, 0, 1)
        cwriter.addData4f(*color)

        # Top circumference
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            vwriter.addData3f(x, y, top_z)
            nwriter.addData3f(0, 0, 1)
            cwriter.addData4f(*color)

        # Bottom center
        vwriter.addData3f(0, 0, bottom_z)
        nwriter.addData3f(0, 0, -1)
        cwriter.addData4f(*color)

        # Bottom circumference
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            vwriter.addData3f(x, y, bottom_z)
            nwriter.addData3f(0, 0, -1)
            cwriter.addData4f(*color)

        # Top fan
        top_triangles = GeomTriangles(Geom.UHStatic)
        for i in range(1, segments + 1):
            next_i = 1 if i == segments else i + 1
            top_triangles.addVertices(0, i, next_i)
            top_triangles.closePrimitive()

        # Bottom fan
        bottom_center = segments + 1
        bottom_triangles = GeomTriangles(Geom.UHStatic)
        for i in range(segments):
            curr = segments + 2 + i
            next_i = segments + 2 if i == segments - 1 else curr + 1
            bottom_triangles.addVertices(bottom_center, next_i, curr)
            bottom_triangles.closePrimitive()

        # Side faces
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

        # Unterseite
        for v in [(0, 0, 0), (width, 0, 0), (width, depth, 0), (0, depth, 0)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, -1)
            col.addData4f(*color)
        # Oberseite
        for v in [(0, 0, height), (width, 0, height), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, 1)
            col.addData4f(*color)
        # Vorderseite
        for v in [(0, 0, 0), (width, 0, 0), (width, 0, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, -1, 0)
            col.addData4f(*color)
        # Rückseite
        for v in [(0, depth, 0), (width, depth, 0), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 1, 0)
            col.addData4f(*color)
        # Linke Seite
        for v in [(0, 0, 0), (0, depth, 0), (0, depth, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(-1, 0, 0)
            col.addData4f(*color)
        # Rechte Seite
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
        # Unterkante
        ls.moveTo(0, 0, 0)
        ls.drawTo(width, 0, 0)
        ls.drawTo(width, depth, 0)
        ls.drawTo(0, depth, 0)
        ls.drawTo(0, 0, 0)
        # Oberkante
        ls.moveTo(0, 0, height)
        ls.drawTo(width, 0, height)
        ls.drawTo(width, depth, height)
        ls.drawTo(0, depth, height)
        ls.drawTo(0, 0, height)
        # Vertikale Kanten
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
        t = task.time
        new_height = 0.5 + 0.5 * math.sin(t * 2.0)
        self.fork_node.setZ(new_height)
        return Task.cont


if __name__ == "__main__":
    app = SimpleSimulation()
    app.run()
