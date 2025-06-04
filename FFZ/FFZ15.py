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
import random
import math


class SimpleSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Initialwerte
        self.sim_clock = 0.0
        self.speed_factor = 1.0
        # Fahrzeug startet mit 1.5 m/s (Standardgeschwindigkeit)
        self.current_speed = 1.5
        # Wir speichern außerdem unsere Hindernisse in einer Liste
        self.obstacles = []

        # Kameraeinstellungen (Fahrtrichtung: entlang der Y-Achse)
        self.cam.setPos(0, -30, 10)
        self.cam.lookAt(0, 0, 0)

        # Licht und Raster
        self.setup_light()
        self.create_grid(center_extent=10, cell_size=0.1)

        # Zufällige Hindernisse erzeugen
        self.create_obstacles()

        # Fahrzeug erstellen (mit Chassis, Fork, Mast, etc.)
        self.vehicle = self.create_vehicle()

        # Slider für Simulationsgeschwindigkeit
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

        # Slider zur manuellen Einstellung der Forkhöhe (0 bis 1 m)
        self.fork_slider = DirectSlider(
            range=(0.0, 1.0),
            value=0.0,
            pageSize=0.01,
            command=self.update_fork_height,
            pos=(-0.7, 0, -0.85),
            scale=0.3
        )
        self.fork_label = DirectLabel(
            text="Fork Höhe: 0.00m",
            pos=(-0.7, 0, -0.75),
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

        # Aufgaben: Simulationszeit, Anzeige und Fahrzeugbewegung (inkl. Hindernisvermeidung)
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
        self.taskMgr.add(self.update_vehicle, "UpdateVehicleTask")
        # Optional: Der Task für die Fork-Animation (update_cable) kann hinzugefügt werden,
        # wenn die Fork zusätzlich oszillieren soll.
        # self.taskMgr.add(self.update_cable, "UpdateCableTask")

    def create_obstacles(self):
        """Erstellt zufällige Hindernisse (Boxen) und platziert sie auf der Ebene (Z=0)."""
        for i in range(10):
            w = random.uniform(0.3, 0.7)
            d = random.uniform(0.3, 0.7)
            h = 0.5
            box = self.create_box(w, d, h, (0.5, 0.5, 0.5, 1))
            obstacle = self.render.attachNewNode(box)
            x = random.uniform(-5, 5)
            y = random.uniform(-5, 5)
            obstacle.setPos(x, y, 0)
            self.obstacles.append(obstacle)

    def update_vehicle(self, task):
        """Bewegt das Fahrzeug vorwärts, passt die Geschwindigkeit gemäß Beschleunigung/Verzögerung an
           und weicht Hindernissen aus."""
        dt = ClockObject.getGlobalClock().getDt()
        pos = self.vehicle.getPos()
        forward = self.vehicle.getQuat().getForward()

        # Hindernisvermeidung: Berechne einen Vermeidungsvektor
        avoid_vector = Vec3(0, 0, 0)
        obstacle_detected = False
        for obstacle in self.obstacles:
            obs_pos = obstacle.getPos(self.render)
            diff = pos - obs_pos
            dist = diff.length()
            # Wenn ein Hindernis in einem Radius von 3 Einheiten liegt und vor dem Fahrzeug ist:
            if dist < 3.0 and diff.dot(forward) > 0:
                obstacle_detected = True
                strength = (3.0 - dist) / 3.0
                avoid_vector += diff.normalized() * strength

        # Bestimme die Zielgeschwindigkeit:
        # Ohne Hindernis soll 1.5 m/s, mit Hindernis 0.5 m/s gelten.
        if obstacle_detected:
            target_speed = 0.5
        else:
            target_speed = 1.5

        # Passe die aktuelle Geschwindigkeit mit einer Beschleunigungsrate von 2 m/s^2 an:
        acceleration_rate = 2.0
        if self.current_speed < target_speed:
            self.current_speed = min(self.current_speed + acceleration_rate * dt, target_speed)
        elif self.current_speed > target_speed:
            self.current_speed = max(self.current_speed - acceleration_rate * dt, target_speed)

        # Bei Hindernisvermeidung lenken: Wenn ein Vermeidungsvektor vorhanden ist,
        # berechne eine gewünschte Richtung
        if avoid_vector.length() > 0:
            desired_dir = (forward + avoid_vector).normalized()
            # Bestimme den gewünschten Heading in Grad (nur in der XY-Ebene)
            desired_heading = math.degrees(math.atan2(desired_dir.getX(), desired_dir.getY()))
            current_heading = self.vehicle.getH()
            # Glätte die Änderung (Interpolation)
            new_heading = current_heading + 0.1 * (desired_heading - current_heading)
            self.vehicle.setH(new_heading)
            forward = self.vehicle.getQuat().getForward()

        # Aktualisiere die Fahrzeugposition basierend auf der aktuellen Geschwindigkeit
        new_pos = pos + forward * self.current_speed * dt
        self.vehicle.setPos(new_pos)

        return Task.cont

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

    def update_fork_height(self, height=0, *args):
        try:
            height = float(height)
        except ValueError:
            height = 0.0
        self.fork_node.setZ(height)
        self.fork_label['text'] = f"Fork Höhe: {height:.2f}m"

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

        # Fahrmodul (Chassis): 1 x 0.5 x 1.2 in Rot
        box_chassis = self.create_box(1, 0.5, 1.2, (1.0, 0.0, 0.0, 1))
        node_chassis = vehicle_node.attachNewNode(box_chassis)
        node_chassis.setTwoSided(True)
        node_chassis.setPos(0, 0, 0)
        # Schwarze Kanten für das Chassis
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

        # Mast: Rahmen aus vier Balken
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

        # Diagonalen auf der oberen Fläche des Mastes
        self.add_diagonals_to_mast(mast_node)
        # Definiere den Schnittpunkt der Diagonalen in lokalen Mast-Koordinaten
        intersection = Vec3(0.5, 0.05, 1.0)

        # Gelber Zylinder: Durchmesser 0.1, Höhe 0.1, Farbe Gelb (1,1,0,1)
        cylinder_node = NodePath(self.create_cylinder(0.1, 0.1, 16, (1, 1, 0, 1)))
        cylinder_node.reparentTo(mast_node)
        cylinder_node.setPos(intersection)

        # Lidar-Kreis: Der Mittelpunkt soll 1 m in negativer Z-Richtung liegen (also z = -1)
        lidar_center = Vec3(intersection.x, intersection.y, -1)
        self.add_lidar_circle(mast_node, lidar_center, 2)

        # Setze den Fahrzeugknoten so, dass er auf der Ebene sitzt (Z=0).
        vehicle_node.setPos(0, 0, 0)

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
            tris.addVertices(base, base+1, base+2)
            tris.closePrimitive()
            tris.addVertices(base, base+2, base+3)
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
