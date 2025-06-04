# environment_visualization.py

from panda3d.core import (
    LineSegs, LColor, Vec3, Vec2, GeomVertexFormat, GeomVertexData,
    GeomVertexWriter, GeomLines, Geom, GeomNode, TextNode, CardMaker,
    AmbientLight, DirectionalLight
)
import math

def attach_label(node, offset=Vec3(1, 0, 0), scale=1):
    """
    Hängt einen Text-Node an den übergebenen Node an, der dessen Namen anzeigt.
    """
    text_node = TextNode("node_label")
    text_node.setText(node.getName())
    text_node.setAlign(TextNode.ACenter)
    text_np = node.attachNewNode(text_node)
    text_np.setScale(scale)
    text_np.setPos(offset)
    text_np.setBillboardAxis()
    return text_np

###############################################################################
# NodeManager
###############################################################################

class NodeManager:
    def __init__(self, render):
        self.render = render
        # Alle erzeugten Nodes werden in diesem Dictionary mit eindeutigen Namen
        # abgelegt.
        self.nodes = {}
        # Zähler zur eindeutigen Namensvergabe
        self.counters = {"blue": 0, "green": 0}

    def register_node(self, node, node_type):
        self.counters[node_type] += 1
        unique_name = f"{node_type}_node_{self.counters[node_type]}"
        node.setName(unique_name)
        self.nodes[unique_name] = node
        return unique_name

    def create_blue_dot(self, loader, pos, scale=0.1):
        blue_dot = loader.loadModel("models/misc/sphere")
        blue_dot.setScale(scale)
        blue_dot.setColor(LColor(0, 0, 1, 1))
        blue_dot.setPos(pos)
        blue_dot.reparentTo(self.render)
        self.register_node(blue_dot, "blue")
        attach_label(blue_dot, Vec3(2, 0, 0), 5)
        return blue_dot

    def create_green_dot(self, loader, pos, scale=0.1):
        green_dot = loader.loadModel("models/misc/sphere")
        green_dot.setScale(scale)
        green_dot.setColor(LColor(0, 1, 0, 1))
        green_dot.setPos(pos)
        green_dot.reparentTo(self.render)
        self.register_node(green_dot, "green")
        attach_label(green_dot, Vec3(2, 0, 0), 5)
        return green_dot

    def list_all_nodes(self):
        return list(self.nodes.keys())

    def get_node(self, unique_name):
        return self.nodes.get(unique_name)

###############################################################################
# EnvironmentVisualizer (überarbeitete Version)
###############################################################################

class EnvironmentVisualizer:
    def __init__(self, render, loader):
        """
        Initialisiert den Visualisierer mit den für Panda3D benötigten Objekten.
        """
        self.render = render
        self.loader = loader
        self.node_manager = NodeManager(render)
        # Hier werden z. B. alle erzeugten Wandsegmente gesammelt.
        self.wall_segments = []

    def setup_environment(self):
        """
        Diese Methode fasst alle Schritte zusammen, die für den Aufbau der Umgebung
        nötig sind. Neben dem Erzeugen von Ursprung, Licht, Boden, Wand, Stations- und Garagen­-objekten
        werden auch diverse Verbindungslinien und Markierungen (zum Beispiel zwischen blauen Punkten)
        erstellt.
        Die Methode gibt ein Dictionary mit allen wichtigen Elementen zurück.
        """
        # Ursprung (Koordinatensystem) zeichnen
        origin_node = self.draw_origin()

        # Licht und Bodenraster erzeugen
        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=70, cell_size=1)

        # Wand erstellen – hier werden die erzeugten Wandsegmente in self.wall_segments gespeichert
        self.create_wall()

        # Annahmestationen erzeugen: Hier gehen wir davon aus, dass die Methode ein Tupel zurückgibt.
        annahme_stations, station_blue_dots = self.create_annahme_stations()
        annahme_dict = {
            "annahme_stations": annahme_stations,
            "station_blue_dots": station_blue_dots,
            "white_lines": None,  # Hier können zusätzliche Objekte ergänzt werden
            "connecting_line": None
        }

        # Abgabestationen erzeugen:
        abgabe_stations, abgabe_blue_dots = self.create_abgabe_stations()
        abgabe_dict = {
            "abgabe_stations": abgabe_stations,
            "abgabe_blue_dots": abgabe_blue_dots,
            "abgabe_white_lines": None,  # Platzhalter für zukünftige Erweiterungen
            "abgabe_extra_blue_dot": None,
            "abgabe_extra_line": None
        }

        # Garagenstationen erzeugen:
        garagen_stations, garagen_parking_points = self.create_garagen_stations()

        # Weitere Objekte:
        edge_between_blue = self.draw_edge_between_blue_nodes("blue_node_26", "blue_node_21")
        self.connect_annahme_abgabe_blue_dots(color=LColor(1, 1, 1, 1), thickness=2.0)
        # Optional: Weitere Verbindungsaufbauten (z. B. für Annahme- und Abgabestationen, Garagen) können hier aufgerufen werden:
        self.connect_annahme_stations(color=LColor(1, 1, 1, 1), thickness=2.0)
        self.connect_abgabe_stations(color=LColor(1, 1, 1, 1), thickness=2.0)
        self.connect_garagen_blue_dots(line_color=LColor(1, 1, 1, 1), thickness=2.0, text_color=LColor(0, 0, 1, 1))

        # Optionale gelbe Punkte:
        yellow_station_points = self.create_yellow_station_points(offset=3.0, scale=0.1)
        yellow_abgabe_points = self.create_yellow_abgabe_points(offset=3.0, scale=0.1)
        yellow_garage_points = self.create_yellow_garage_points(offset=3.0, scale=0.1)

        # Alle Objekte in einem Dictionary zusammenfassen:
        env = {
            "origin": origin_node,
            "wall_segments": self.wall_segments,
            "annahme_stations": annahme_dict["annahme_stations"],
            "station_blue_dots": annahme_dict["station_blue_dots"],
            "white_lines": annahme_dict["white_lines"],
            "annahme_connecting_line": annahme_dict.get("connecting_line"),
            "abgabe_stations": abgabe_dict["abgabe_stations"],
            "abgabe_blue_dots": abgabe_dict["abgabe_blue_dots"],
            "abgabe_white_lines": abgabe_dict["abgabe_white_lines"],
            "abgabe_extra_blue_dot": abgabe_dict["abgabe_extra_blue_dot"],
            "abgabe_extra_line": abgabe_dict["abgabe_extra_line"],
            "garagen_stations": garagen_stations,
            "garagen_parking_points": garagen_parking_points,
            "edge_between_blue": edge_between_blue,
            "yellow_station_points": yellow_station_points,
            "yellow_abgabe_points": yellow_abgabe_points,
            "yellow_garage_points": yellow_garage_points
        }
        return env

    # ---------------------------------------------------------------------------
    # Basisaufbau
    # ---------------------------------------------------------------------------
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
        origin_np = self.render.attachNewNode(ls.create())
        return origin_np

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

        return alight_np, dlight_np

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

    def add_wall_segment(self, start, end, height=2.0, thickness=0.5):
        seg_vector = end - start
        length = seg_vector.length()
        if length == 0:
            return None
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
        if not hasattr(self, 'wall_segments'):
            self.wall_segments = []
        self.wall_segments.append(wall_np)
        return wall_np

    def create_wall(self):
        p1 = Vec3(0, 0, 0)
        p2 = Vec3(0, 60, 0)
        p3 = Vec3(22, 60, 0)
        p4 = Vec3(22, 0, 0)
        seg1 = self.add_wall_segment(p1, p2)
        seg2 = self.add_wall_segment(p2, p3)
        seg3 = self.add_wall_segment(p3, p4)
        seg4 = self.add_wall_segment(p4, p1)
        return [seg1, seg2, seg3, seg4]

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
        station_np = self.render.attachNewNode(ls.create())
        return station_np

    def create_annahme_stations(self):
        station_points = [
            Vec3(0, 5, 0), Vec3(0, 10, 0), Vec3(0, 15, 0),
            Vec3(0, 20, 0), Vec3(0, 25, 0), Vec3(0, 30, 0),
            Vec3(0, 35, 0), Vec3(0, 40, 0), Vec3(0, 45, 0),
            Vec3(0, 50, 0)
        ]
        annahme_stations = []
        station_blue_dots = {}
        self.annahme_blue_dot_list = []  # Für spätere Verbindungen

        for i, pt in enumerate(station_points, start=1):
            self.create_annahme_station(pt)  # Zeichnet den Basisrahmen
            station_dummy = self.render.attachNewNode(f"annahme_station_{i}")
            station_dummy.setPos(pt)
            annahme_stations.append(station_dummy)

            center = pt + Vec3(0.5, 0.5, 0.5)
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)

            green_dot = self.node_manager.create_green_dot(self.loader, center + Vec3(0, 0, -0.5), 0.1)

            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, -0.5)
            end_line = start_line + Vec3(3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())

            station_dummy.setPythonTag("white_center", (start_line + end_line) * 0.5)
            line_vec = end_line - start_line
            if line_vec.length() != 0:
                station_dummy.setPythonTag("white_direction", Vec2(line_vec.getX(), line_vec.getY()).normalized())
            else:
                station_dummy.setPythonTag("white_direction", Vec2(1, 0))

            blue_dot = self.node_manager.create_blue_dot(self.loader, end_line)
            station_blue_dots[station_dummy] = blue_dot
            self.annahme_blue_dot_list.append(blue_dot)

            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 1.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

            # Zusätzliche Markierungen (z. B. Kreuze) – hier als Beispiel:
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

            if i == 1:
                self.blue_dot = blue_dot
                self.station_green_dot = green_dot
                self.white_line_center = (start_line + end_line) * 0.5
                if line_vec.length() != 0:
                    self.station_white_direction = Vec2(line_vec.getX(), line_vec.getY()).normalized()
                else:
                    self.station_white_direction = Vec2(1, 0)

        return annahme_stations, station_blue_dots

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
        abgabe_np = self.render.attachNewNode(ls.create())
        return abgabe_np

    def create_abgabe_stations(self):
        station_points = [
            Vec3(21, 5, 0), Vec3(21, 10, 0), Vec3(21, 15, 0),
            Vec3(21, 20, 0), Vec3(21, 25, 0), Vec3(21, 30, 0),
            Vec3(21, 35, 0), Vec3(21, 40, 0), Vec3(21, 45, 0),
            Vec3(21, 50, 0)
        ]
        abgabe_stations = []
        abgabe_blue_dots = []

        for i, pt in enumerate(station_points, start=1):
            node = self.create_abgabe_station(pt)
            abgabe_stations.append(node)
            center = pt + Vec3(0.5, 0.5, 0.5)
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)

            green_dot = self.node_manager.create_green_dot(self.loader, center + Vec3(0, 0, -0.5), 0.1)

            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, -0.5)
            end_line = start_line + Vec3(-3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())

            blue_dot = self.node_manager.create_blue_dot(self.loader, end_line)
            abgabe_blue_dots.append(blue_dot)

            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x - 0.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

            # Optionale zusätzliche Markierungen:
            self.add_cross_on_face([pt + Vec3(1, 0, 0), pt + Vec3(1, 1, 0), pt + Vec3(1, 1, 1), pt + Vec3(1, 0, 1)],
                                   color=LColor(1, 0, 0, 1))
            self.add_cross_on_face([pt + Vec3(0, 0, 0), pt + Vec3(1, 0, 0), pt + Vec3(1, 0, 1), pt + Vec3(0, 0, 1)],
                                   color=LColor(1, 0, 0, 1))
            self.add_cross_on_face([pt + Vec3(0, 1, 0), pt + Vec3(1, 1, 0), pt + Vec3(1, 1, 1), pt + Vec3(0, 1, 1)],
                                   color=LColor(1, 0, 0, 1))

        return abgabe_stations, abgabe_blue_dots

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
        self.garagen_blue_dots = []  # Liste zum Speichern der blauen Marker für die Garagen

        self.garagen_stations = []
        self.garagen_parking_points = []
        for i, pt in enumerate(station_points, start=1):
            self.create_garage_station(pt)
            self.add_garage_roof(pt)
            self.garagen_stations.append(pt)
            # ParkpunktGarage: Verschoben um 0.5 in negativer Y-Richtung:
            center = pt + Vec3(0.5, 0.5, 1.5)
            ParkpunktGarage = center + Vec3(0, 0, 0.7)
            # Neuer Startpunkt: Unterer Mittelpunkt der Garage (z = 0)
            garage_base_center = pt + Vec3(0.5, 1.0, 0)  # wichtig als Ausgangspunkt für die Linien plus blauen Punkte davor

            self.garagen_parking_points.append(ParkpunktGarage)
            # Zeichne die weiße Linie: Sie beginnt am Parkpunkt der Garage und verläuft 3 Meter in X‑Richtung.
            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = garage_base_center
            end_line = start_line + Vec3(0, -3, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())

            blue_dot = self.node_manager.create_blue_dot(self.loader, end_line)
            self.garagen_blue_dots.append(blue_dot)


            tn = TextNode("garage_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 0.5, pt.y - 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)
        # Am Ende sicherstellen, dass ein Tupel zurückgegeben wird:
        return self.garagen_stations, self.garagen_parking_points

    def add_cross_on_face(self, corners, color=LColor(1, 1, 1, 1), thickness=1.5):
        """
        Zeichnet ein Kreuz (d.h. zwei Diagonallinien) auf der Fläche, definiert durch vier Eckpunkte in 'corners'.

        Parameters:
          corners (list of Vec3): Liste der vier Eckpunkte.
          color (LColor): Farbe des Kreuzes.
          thickness (float): Linienstärke.

        Returns:
          NodePath: Der NodePath, der die gezeichneten Linien beinhaltet.
        """
        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(corners[0])
        ls.drawTo(corners[2])
        ls.moveTo(corners[1])
        ls.drawTo(corners[3])
        return self.render.attachNewNode(ls.create())

    def create_yellow_end_points_on_line(self, start_dot, end_dot, offset=3.0, scale=0.1):
        """
        Zeichnet gelbe Punkte an beiden Enden der Verbindungslinie.

        Die Punkte werden 3 Meter (offset) in Richtung des Verbindungsmittelpunktes gesetzt:
          - Vom Startmarker: Verschiebung in Richtung des Endmarkers.
          - Vom Endmarker: Verschiebung entgegengesetzt zur Verbindungsrichtung.

        Um doppelte Beschriftungen zu vermeiden, werden alle automatisch angehängten
        Label-Knoten (mit dem Namen "node_label") entfernt.

        Rückgabe:
          Ein Tupel (yellow_point_start, yellow_point_end)
        """
        # Ermittle die Weltpositionen der beiden Marker:
        start_pos = start_dot.getPos(self.render)
        end_pos = end_dot.getPos(self.render)

        # Berechne den Richtungsvektor und normalisiere ihn:
        direction = end_pos - start_pos
        norm = direction.length()
        if norm == 0:
            print("Start- und Endpunkt sind identisch, gelbe Punkte können nicht berechnet werden.")
            return None, None
        direction_normalized = direction / norm

        # Setze die gelben Punkte 3 Meter in Richtung des Mittelpunkts der Verbindung:
        yellow_start_pos = start_pos + (direction_normalized * offset)
        yellow_end_pos = end_pos - (direction_normalized * offset)

        # Erzeuge die Punkte über den NodeManager
        yellow_point_start = self.node_manager.create_blue_dot(self.loader, yellow_start_pos, scale)
        # Entferne automatisch angehängte Label-Knoten (sofern vorhanden)
        for child in yellow_point_start.getChildren():
            if child.getName() == "node_label":
                child.removeNode()
        yellow_point_start.setColor(LColor(1, 1, 0, 1))  # Gelb

        yellow_point_end = self.node_manager.create_blue_dot(self.loader, yellow_end_pos, scale)
        for child in yellow_point_end.getChildren():
            if child.getName() == "node_label":
                child.removeNode()
        yellow_point_end.setColor(LColor(1, 1, 0, 1))  # Gelb

        return yellow_point_start, yellow_point_end

    def connect_annahme_abgabe_blue_dots(self, color=LColor(1, 1, 1, 1), thickness=2.0, text_color=LColor(0, 0, 1, 1)):
        """
        Verbindet jeden blauen Marker der Annahmestationen mit dem entsprechenden blauen Marker
        der Abgabestationen, zeichnet dabei die Verbindungslinie (mit Label "Verbindung X")
        und erzeugt pro Verbindungslinie genau zwei gelbe Punkte.

        Es wird über alle Verbindungslinien hinweg fortlaufend nummeriert, sodass der erste
        gelbe Punkt "yellow_node_1", der zweite "yellow_node_2", der dritte "yellow_node_3" usw.
        lautet.

        Die erzeugten gelben Punkte werden als Tupel in der Instanzvariablen
        self.annahme_abgabe_yellow_points gespeichert.
        """
        # Überprüfe, ob beide Listen vorhanden sind:
        if not hasattr(self, "annahme_blue_dot_list") or not hasattr(self, "abgabe_blue_dots"):
            print("Es sind nicht alle blauen Punkte vorhanden!")
            return

        if len(self.annahme_blue_dot_list) != len(self.abgabe_blue_dots):
            print("Die Anzahl der blauen Punkte der Annahme- und Abgabestationen stimmt nicht überein!")
            return

        from panda3d.core import TextNode, Vec3
        yellow_points = []  # Hier werden die Tupel gelber Punkte gesammelt
        global_yellow_counter = 1  # Globaler Zähler über alle Verbindungslinien

        for idx, (blue_annahme, blue_abgabe) in enumerate(zip(self.annahme_blue_dot_list, self.abgabe_blue_dots),
                                                          start=1):
            # Zeichne die Verbindungslinie zwischen den blauen Punkten:
            ls = LineSegs()
            ls.setThickness(thickness)
            ls.setColor(color)
            ls.moveTo(blue_annahme.getPos())
            ls.drawTo(blue_abgabe.getPos())
            self.render.attachNewNode(ls.create())

            # Berechne den Mittelpunkt und erstelle ein Label für die Verbindung (z. B. "Verbindung 1")
            pos_a = blue_annahme.getPos(self.render)
            pos_b = blue_abgabe.getPos(self.render)
            midpoint = (pos_a + pos_b) * 0.5

            label_text = f"Verbindung {idx}"
            tn = TextNode("line_label")
            tn.setText(label_text)
            tn.setAlign(TextNode.ACenter)
            label_np = blue_annahme.attachNewNode(tn)
            relative_offset = blue_annahme.getRelativePoint(self.render, midpoint)
            label_np.setPos(relative_offset)
            label_np.setScale(5)
            label_np.setBillboardPointEye()

            # Erzeuge exakt zwei gelbe Punkte für diese Verbindungslinie:
            yellow_start, yellow_end = self.create_yellow_end_points_on_line(
                blue_annahme, blue_abgabe, offset=3.0, scale=0.1
            )

            # Beschrifte den ersten gelben Punkt mit der globalen Nummer und erhöhe den Zähler:
            tn_yellow_start = TextNode("yellow_label")
            tn_yellow_start.setText(f"yellow_node_{global_yellow_counter}")
            tn_yellow_start.setAlign(TextNode.ACenter)
            label_np_start = yellow_start.attachNewNode(tn_yellow_start)
            label_np_start.setScale(3)
            label_np_start.setBillboardPointEye()
            global_yellow_counter += 1

            # Beschrifte den zweiten gelben Punkt:
            tn_yellow_end = TextNode("yellow_label")
            tn_yellow_end.setText(f"yellow_node_{global_yellow_counter}")
            tn_yellow_end.setAlign(TextNode.ACenter)
            label_np_end = yellow_end.attachNewNode(tn_yellow_end)
            label_np_end.setScale(3)
            label_np_end.setBillboardPointEye()
            global_yellow_counter += 1

            yellow_points.append((yellow_start, yellow_end))

        self.annahme_abgabe_yellow_points = yellow_points
        return yellow_points

    def connect_garagen_blue_dots(self, line_color=LColor(1, 1, 1, 1), thickness=2.0, text_color=LColor(0, 0, 1, 1)):
        """
        Verbindet alle blauen Punkte der Garagen (self.garagen_blue_dots) mit einer durchgehenden Linie
        in der Farbe `line_color` und versieht jeden Abschnitt zwischen zwei benachbarten blauen Punkten
        mit einer Beschriftung. Die Nummerierung der Beschriftungen beginnt bei 11 (also "Verbindung 11",
        "Verbindung 12" usw.). Nur die Schrift wird in der Farbe `text_color` (blau) dargestellt,
        die Linie behält ihre eigene Farbe.

        Parameter:
          line_color (LColor): Farbe der Verbindungslinie, standardmäßig Weiß.
          thickness (float): Dicke der Verbindungslinie, standardmäßig 2.0.
          text_color (LColor): Farbe der Beschriftung, standardmäßig Blau.
        """
        from panda3d.core import TextNode, Vec3

        # Überprüfe, ob die Liste der Garagen-Blaupunkte existiert und Elemente enthält
        if not hasattr(self, "garagen_blue_dots") or not self.garagen_blue_dots:
            print("Keine blauen Punkte der Garagen vorhanden!")
            return

        # Erstelle die durchgehende Linie in der Farbe line_color
        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(line_color)

        first_pos = self.garagen_blue_dots[0].getPos(self.render)
        ls.moveTo(first_pos)
        for blue_dot in self.garagen_blue_dots[1:]:
            ls.drawTo(blue_dot.getPos(self.render))
        self.render.attachNewNode(ls.create())

        # Für jeden Abschnitt zwischen zwei benachbarten blauen Punkten:
        for i in range(len(self.garagen_blue_dots) - 1):
            pos1 = self.garagen_blue_dots[i].getPos(self.render)
            pos2 = self.garagen_blue_dots[i + 1].getPos(self.render)
            midpoint = (pos1 + pos2) * 0.5

            # Erzeuge das Label mit der entsprechenden Nummerierung (beginnend bei 11)
            label_text = f"Verbindung {i + 11}"
            tn = TextNode("garage_line_label")
            tn.setText(label_text)
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(text_color)

            # Hänge das Label an den Render-Knoten, damit die Platzierung in Weltkoordinaten erfolgt
            label_np = self.render.attachNewNode(tn)
            # Positioniere das Label am Mittelpunkt der Verbindung mit einem kleinen Z-Offset
            label_np.setPos(midpoint + Vec3(0, 0, 0.5))
            # Setze die Skalierung entsprechend (hier z. B. 0.3, anpassbar je nach Bedarf)
            label_np.setScale(0.3)
            # Richte den Text mittels Billboarding so aus, dass er immer zur Kamera zeigt
            label_np.setBillboardPointEye()

    def connect_annahme_stations(self, color=LColor(1, 1, 1, 1), thickness=2.0):
        """
        Verbindet alle blauen Marker der Annahmestationen (gespeichert in self.annahme_blue_dot_list)
        mit einer durchgehenden Linie in der angegebenen Farbe und Dicke.

        Parameter:
          color (LColor): Farbe der Verbindungslinie, standardmäßig Weiß (LColor(1, 1, 1, 1)).
          thickness (float): Dicke der Linie, standardmäßig 2.0.
        """
        # Prüfen, ob überhaupt blaue Marker für die Annahmestationen vorhanden sind
        if not hasattr(self, "annahme_blue_dot_list") or not self.annahme_blue_dot_list:
            print("Keine blauen Marker der Annahmestationen vorhanden!")
            return

        from panda3d.core import LineSegs

        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)

        # Verwende die Weltkoordinaten der blauen Marker, um den Pfad zu erstellen
        first_pos = self.annahme_blue_dot_list[0].getPos(self.render)
        ls.moveTo(first_pos)
        for blue_dot in self.annahme_blue_dot_list[1:]:
            ls.drawTo(blue_dot.getPos(self.render))

        # Hänge den erzeugten Linien-Node an den Render-Knoten, sodass die Linie in der Szene sichtbar wird
        self.render.attachNewNode(ls.create())

    def connect_abgabe_stations(self, color=LColor(1, 1, 1, 1), thickness=2.0):
        """
        Verbindet alle blauen Marker der Abgabestationen (gespeichert in self.abgabe_blue_dots)
        mit einer durchgehenden Linie in der angegebenen Farbe und Dicke.

        Parameter:
          color (LColor): Farbe der Verbindungslinie, standardmäßig Weiß (LColor(1, 1, 1, 1)).
          thickness (float): Dicke der Verbindungslinie, standardmäßig 2.0.
        """
        # Prüfe, ob die Liste der Abgabestationen-Blaupunkte existiert und Elemente enthält
        if not hasattr(self, "abgabe_blue_dots") or not self.abgabe_blue_dots:
            print("Keine blauen Marker der Abgabestationen vorhanden!")
            return

        from panda3d.core import LineSegs

        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)

        # Starte am ersten blauen Marker
        first_pos = self.abgabe_blue_dots[0].getPos(self.render)
        ls.moveTo(first_pos)
        # Verbinde alle folgenden blauen Marker in ihrer Reihenfolge
        for blue_dot in self.abgabe_blue_dots[1:]:
            ls.drawTo(blue_dot.getPos(self.render))

        # Hänge den Linien-Node an den Render-Knoten, sodass die Linie in der Szene angezeigt wird
        self.render.attachNewNode(ls.create())

    def create_fixed_blue_dot(self, pos=Vec3(18.5, 54.5, 0), scale=0.1):
        """
        Erstellt (falls noch nicht vorhanden) einen blauen Punkt an der festen Position (18,55,0)
        und speichert ihn als Attribut (self._fixed_blue_dot). Wird er bereits existieren,
        so wird dieser wieder zurückgegeben.

        Parameter:
          pos   - Zielposition (Default: Vec3(18,55,0))
          scale - Skalierung des blauen Punktes (Default: 0.1)

        Rückgabe:
          NodePath des fixierten blauen Punktes.
        """
        if hasattr(self, '_fixed_blue_dot') and self._fixed_blue_dot is not None:
            return self._fixed_blue_dot
        blue_dot = self.node_manager.create_blue_dot(self.loader, pos, scale)
        self._fixed_blue_dot = blue_dot
        return blue_dot

    def create_fixed_connection_line(self, abgabe_index=10, thickness=2.0, color=LColor(1, 1, 1, 1)):
        # Überprüfe, ob genügend Abgabestations-Markierungen vorhanden sind.
        if not hasattr(self, 'abgabe_blue_dots') or len(self.abgabe_blue_dots) < abgabe_index:
            print(f"Abgabestation {abgabe_index} existiert nicht!")
            return None

        # Hole den blauen Marker der gewünschten Abgabestation (Index abgabe_index-1)
        abgabe_dot = self.abgabe_blue_dots[abgabe_index - 1]

        # Verwende den bereits erzeugten fixierten blauen Punkt
        fixed_dot = self.create_fixed_blue_dot()

        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(abgabe_dot.getPos(self.render))
        ls.drawTo(fixed_dot.getPos(self.render))
        connection_line = self.render.attachNewNode(ls.create())
        return connection_line

    def create_garage5_connection_line(self, thickness=2.0, color=LColor(1, 1, 1, 1)):
        """
        Erstellt eine Verbindungslinie zwischen dem fixierten blauen Punkt (z. B. an (18,55,0))
        und dem blauen Marker der fünften Garage.

        Voraussetzung:
          - Es existiert bereits ein fixierter blauer Punkt (mittels create_fixed_blue_dot())
          - Die Liste self.garagen_blue_dots enthält mindestens 5 Einträge, wobei der
            fünfte Marker (Index 4) den blauen Marker der fünften Garage repräsentiert.

        Rückgabe:
          NodePath des Linien-Objekts.
        """
        # Prüfe, ob mindestens 5 Garagen-Blaupunkte vorhanden sind.
        if not hasattr(self, 'garagen_blue_dots') or len(self.garagen_blue_dots) < 5:
            print("Nicht genügend Garage-Markierungen vorhanden!")
            return None

        # Hole den fixierten blauen Punkt – dieser wird über create_fixed_blue_dot() erstellt/abgerufen.
        fixed_point = self.create_fixed_blue_dot()

        # Hole den blauen Marker der 5. Garage (Index 4, da Listen bei 0 beginnen)
        garage5_dot = self.garagen_blue_dots[4]

        # Zeichne die Verbindungslinie von fixed_point zu garage5_dot.
        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(fixed_point.getPos(self.render))
        ls.drawTo(garage5_dot.getPos(self.render))

        connection_line = self.render.attachNewNode(ls.create())
        return connection_line

    def create_connection_line_first_garage_to_10_annahme(self, thickness=2.0, color=LColor(1, 1, 1, 1)):
        """
        Erstellt eine Verbindungslinie zwischen:
          • Dem blauen Marker der ersten Garage (aus self.garagen_blue_dots, Index 0)
          • Dem blauen Marker der 10. Annahmestation (aus self.annahme_blue_dot_list, Index 9)

        Parameter:
          thickness (float): Linienstärke (Standard: 2.0)
          color     (LColor): Farbe der Linie (Standard: Weiß, LColor(1, 1, 1, 1))

        Rückgabe:
          NodePath des Linien-Objekts oder None, wenn die notwendigen Marker nicht existieren.
        """
        # Überprüfe, ob der erste Garage-Blaupunkt existiert.
        if not hasattr(self, 'garagen_blue_dots') or len(self.garagen_blue_dots) < 1:
            print("Der blauen Marker der ersten Garage existiert nicht!")
            return None

        # Überprüfe, ob mindestens 10 Annahme-Blaupunkte existieren.
        if not hasattr(self, 'annahme_blue_dot_list') or len(self.annahme_blue_dot_list) < 10:
            print("Nicht genügend Annahmestationen vorhanden (mindestens 10 erforderlich)!")
            return None

        start_dot = self.garagen_blue_dots[0]
        end_dot = self.annahme_blue_dot_list[9]

        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(start_dot.getPos(self.render))
        ls.drawTo(end_dot.getPos(self.render))

        connection_line = self.render.attachNewNode(ls.create())
        return connection_line

    def create_yellow_station_points(self, offset=3.0, scale=0.1):
        """
        Erstellt für jeden blauen Punkt der Annahmestationen einen gelben Punkt,
        der 3 Meter (offset) in positiver Y-Richtung von dem blauen Punkt entfernt liegt.

        Für jeden gelben Punkt wird ein Label in der Form
            "yellow_station_node_X"
        angehängt, wobei X global fortlaufend gezählt wird.

        Rückgabe:
          Eine Liste mit den NodePaths der erzeugten gelben Punkte.
        """
        from panda3d.core import TextNode, Vec3
        yellow_station_points = []
        global_counter = 1  # Globaler Zähler über alle Annahmestationen

        # Iteriere über alle blauen Punkte der Annahmestationen
        for blue_dot in self.annahme_blue_dot_list:
            # Hole die Weltposition des blauen Punktes
            pos = blue_dot.getPos(self.render)
            # Offener Offset in Y-Richtung (positiv)
            new_pos = pos + Vec3(0, offset, 0)
            # Erzeuge einen gelben Punkt an dieser Position
            yellow_point = self.node_manager.create_blue_dot(self.loader, new_pos, scale)
            # Optional: Entferne den standardmäßig angehängten Label-Knoten,
            # falls dieser vorhanden ist.
            for child in yellow_point.getChildren():
                if child.getName() == "node_label":
                    child.removeNode()
            yellow_point.setColor(LColor(1, 1, 0, 1))  # Setze Farbe Gelb

            # Erzeuge ein Label in der Form "yellow_station_node_X"
            tn = TextNode("yellow_station_label")
            tn.setText(f"yellow_station_node_{global_counter}")
            tn.setAlign(TextNode.ACenter)
            label_np = yellow_point.attachNewNode(tn)
            label_np.setScale(3)
            label_np.setBillboardPointEye()

            yellow_station_points.append(yellow_point)
            global_counter += 1

        return yellow_station_points

    def create_yellow_abgabe_points(self, offset=3.0, scale=0.1):
        """
        Erstellt für jeden blauen Punkt der Abgabestationen einen gelben Punkt,
        der 3 Meter (offset) in positiver Y-Richtung vom blauen Marker entfernt ist.

        Für jeden gelben Punkt wird ein Label in der Form
            "yellow_abgabe_node_X"
        angehängt, wobei X global fortlaufend nummeriert wird (über alle Abgabestationen).

        Rückgabe:
          Eine Liste der NodePaths der erzeugten gelben Abgabe-Punkte.
        """
        from panda3d.core import TextNode, Vec3
        yellow_abgabe_points = []
        global_counter = 1  # Globaler Zähler für die Nummerierung

        # Iteriere über alle blauen Punkte, die Abgabestationen repräsentieren
        for blue_dot in self.abgabe_blue_dots:
            # Ermittele die Weltposition des blauen Punktes
            pos = blue_dot.getPos(self.render)
            # Verschiebe den Punkt um den angegebenen Offset in positiver Y-Richtung
            new_pos = pos + Vec3(0, offset, 0)
            # Erzeuge den gelben Punkt (ohne zusätzliche Label, da diese später entfernt werden)
            yellow_point = self.node_manager.create_blue_dot(self.loader, new_pos, scale)
            # Entferne automatisch angehängte Label (z. B. "node_label"), wenn vorhanden
            for child in yellow_point.getChildren():
                if child.getName() == "node_label":
                    child.removeNode()
            yellow_point.setColor(LColor(1, 1, 0, 1))  # Setze die Farbe auf Gelb

            # Erzeuge ein Label im Format "yellow_abgabe_node_X"
            tn = TextNode("yellow_abgabe_label")
            tn.setText(f"yellow_abgabe_node_{global_counter}")
            tn.setAlign(TextNode.ACenter)
            label_np = yellow_point.attachNewNode(tn)
            label_np.setScale(3)
            label_np.setBillboardPointEye()

            yellow_abgabe_points.append(yellow_point)
            global_counter += 1

        return yellow_abgabe_points

    def create_yellow_garage_points(self, offset=3.0, scale=0.1):
        """
        Erstellt für jeden blauen Punkt der Garagen (aus self.garagen_blue_dots) einen gelben Punkt,
        der 3 Meter in positiver X-Richtung vom blauen Punkt entfernt liegt.

        Der gelbe Punkt für Garage 5 (also der fünfte Punkt in der Liste) wird ausgelassen.

        Für jeden erstellten gelben Punkt wird ein Label im Format "yellow_garage_node_X" angehängt,
        wobei X global fortlaufend gezählt wird.

        Rückgabe:
          Eine Liste der NodePaths der erzeugten gelben Garage-Punkte.
        """
        from panda3d.core import TextNode, Vec3
        yellow_garage_points = []
        global_counter = 1  # global fortlaufender Zähler für die Beschriftung

        # Iteriere über alle blauen Garagen-Punkte anhand ihrer Reihenfolge in der Liste
        for idx, blue_dot in enumerate(self.garagen_blue_dots):
            # Überspringe den blauen Punkt der Garage 5 (bei Index 4, da Zählung bei 0 beginnt)
            if idx == 4:
                continue

            # Hole die Weltposition des aktuellen blauen Punktes
            pos = blue_dot.getPos(self.render)
            # Verschiebe 3 Meter in positiver X-Richtung:
            new_pos = pos + Vec3(offset, 0, 0)

            # Erzeuge den gelben Punkt an der neuen Position
            yellow_point = self.node_manager.create_blue_dot(self.loader, new_pos, scale)
            # Entferne automatisch angehängte Label-Knoten (falls vorhanden)
            for child in yellow_point.getChildren():
                if child.getName() == "node_label":
                    child.removeNode()
            # Setze die Farbe auf Gelb:
            yellow_point.setColor(LColor(1, 1, 0, 1))

            # Erzeuge ein Label im Format "yellow_garage_node_X"
            tn = TextNode("yellow_garage_label")
            tn.setText(f"yellow_garage_node_{global_counter}")
            tn.setAlign(TextNode.ACenter)
            label_np = yellow_point.attachNewNode(tn)
            label_np.setScale(3)
            label_np.setBillboardPointEye()

            yellow_garage_points.append(yellow_point)
            global_counter += 1

        return yellow_garage_points

