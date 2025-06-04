from panda3d.core import Vec3


# ------------------------------
# 1. RouteSegment-Klasse und Hilfsfunktionen
# ------------------------------

class RouteSegment:
    def __init__(self, name, start, end, allowed_direction, stop_threshold=0.5):
        """
        :param name: Eindeutiger Bezeichner des Abschnitts (z. B. "garage_segment_1").
        :param start: Startpunkt des Abschnitts (Vec3).
        :param end: Endpunkt des Abschnitts (Vec3).
        :param allowed_direction: Ein Vec3, der die erlaubte Fahrtrichtung angibt (wird normalisiert).
        :param stop_threshold: Abstand, ab dem der Abschnitt als "durchfahren" gilt.
        """
        self.name = name
        self.start = start
        self.end = end
        self.allowed_direction = allowed_direction.normalized()
        self.stop_threshold = stop_threshold
        self.occupied = False
        self.current_vehicle = None

    def reserve(self, vehicle):
        if not self.occupied:
            self.occupied = True
            self.current_vehicle = vehicle
            print(f"Segment '{self.name}' wurde von {vehicle} reserviert.")
            return True
        print(f"Segment '{self.name}' ist bereits belegt von {self.current_vehicle}.")
        return False

    def release(self):
        print(f"Segment '{self.name}' wird freigegeben von {self.current_vehicle}.")
        self.occupied = False
        self.current_vehicle = None

    def is_free(self):
        return not self.occupied


def create_route_segment_by_names(node_manager, render, segment_name, start_node_name, end_node_name, allowed_direction,
                                  stop_threshold=0.5):
    """
    Erstellt ein RouteSegment anhand der Bezeichnungen von zwei Knoten.

    :param node_manager: Dein NodeManager, der die Knoten verwaltet.
    :param render: Referenz auf dein Render-Objekt.
    :param segment_name: Name des zu erzeugenden Segments.
    :param start_node_name: Name des Start-Knotens (z. B. "blue_node_21").
    :param end_node_name: Name des End-Knotens (z. B. "yellow_node_21").
    :param allowed_direction: Ein Vec3, der die erlaubte Fahrtrichtung definiert.
    :param stop_threshold: Abstand, ab dem der Abschnitt als abgeschlossen gilt.
    :return: Das erzeugte RouteSegment oder None, falls einer der Knoten nicht gefunden wurde.
    """
    start_node = node_manager.get_node(start_node_name)
    end_node = node_manager.get_node(end_node_name)

    if start_node is None or end_node is None:
        print(f"Knoten nicht gefunden: {start_node_name} oder {end_node_name}")
        return None

    start_pos = start_node.getPos(render)
    end_pos = end_node.getPos(render)

    return RouteSegment(segment_name, start_pos, end_pos, allowed_direction, stop_threshold)


def define_garage_route_segments(node_manager, render): # nicht nur garagen Segmente, muss noch geändert werden
    """
    Definiert 8 Garagenstreckenabschnitte anhand von Knotenbezeichnungen.
    Beispiel:
      - Segment 1: von "blue_node_22" bis "yellow_node_21"
      - Segment 2: von "blue_node_23" bis "blue_node_23"
      - Segment 3: von "blue_node_23" bis "yellow_node_22"
      - Segment 4: von "yellow_node_22" bis "blue_node_24"
      - Segment 5: von "blue_node_24" bis "yellow_node_23"
      - Segment 6: von "yellow_node_23" bis "blue_node_25"
      - Segment 7: von "blue_node_25" bis "yellow_node_24"
      - Segment 8: von "yellow_node_24" bis "blue_node_26"

    :return: Ein Dictionary, das alle erstellten Segmente enthält.
    """
    segments = {}

    allowed_direction_1 = Vec3(-1, 0, 0)
    seg1 = create_route_segment_by_names(node_manager, render, "garage_segment_1",
                                         "blue_node_22", "yellow_node_21", allowed_direction_1)
    if seg1:
        segments["garage_segment_1"] = seg1

    allowed_direction_2 = Vec3(-1, 0, 0)
    seg2 = create_route_segment_by_names(node_manager, render, "garage_segment_2",
                                         "blue_node_23", "blue_node_23", allowed_direction_2)
    if seg2:
        segments["garage_segment_2"] = seg2

    allowed_direction_3 = Vec3(-1, 0, 0)
    seg3 = create_route_segment_by_names(node_manager, render, "garage_segment_3",
                                         "blue_node_23", "yellow_node_22", allowed_direction_3)
    if seg3:
        segments["garage_segment_3"] = seg3

    allowed_direction_4 = Vec3(-1, 0, 0)
    seg4 = create_route_segment_by_names(node_manager, render, "garage_segment_4",
                                         "yellow_node_22", "blue_node_24", allowed_direction_4)
    if seg4:
        segments["garage_segment_4"] = seg4

    allowed_direction_5 = Vec3(-1, 0, 0)
    seg5 = create_route_segment_by_names(node_manager, render, "garage_segment_5",
                                         "blue_node_24", "yellow_node_23", allowed_direction_5)
    if seg5:
        segments["garage_segment_5"] = seg5

    allowed_direction_6 = Vec3(-1, 0, 0)
    seg6 = create_route_segment_by_names(node_manager, render, "garage_segment_6",
                                         "yellow_node_23", "blue_node_25", allowed_direction_6)
    if seg6:
        segments["garage_segment_6"] = seg6

    allowed_direction_7 = Vec3(-1, 0, 0)
    seg7 = create_route_segment_by_names(node_manager, render, "garage_segment_7",
                                         "blue_node_25", "yellow_node_24", allowed_direction_7)
    if seg7:
        segments["garage_segment_7"] = seg7

    allowed_direction_8 = Vec3(-1, 0, 0)
    seg8 = create_route_segment_by_names(node_manager, render, "garage_segment_8",
                                         "yellow_node_24", "blue_node_26", allowed_direction_8)
    if seg8:
        segments["garage_segment_8"] = seg8

    return segments

def define_annahme_route_segments(node_manager, render):
    """
    Definiert Annahme-Streckenabschnitte anhand von Knotenbezeichnungen.
    Die Segmente verbinden jeweils einen blauen Knoten mit einem gelben Knoten und folgen einer negativen y-Richtung.

    Beispiel:
      - Segment 1: von "blue_node_1" bis "yellow_node_1"
      - Segment 2: von "yellow_node_1" bis "blue_node_2"
      - Segment 3: von "blue_node_2" bis "yellow_node_2"
      ...
      - Segment 10: von "blue_node_10" bis "yellow_node_10"

      - Nach blue node 10 zu yellow node 10 noch das zusatzverbindungsstück zu den Garagen erstellt

    :return: Ein Dictionary, das alle erstellten Segmente enthält.
    """
    segments = {}

    allowed_direction = Vec3(0, -1, 0)  # Negative y-Richtung

    seg1 = create_route_segment_by_names(node_manager, render, "annahme_segment_1",
                                         "blue_node_1", "yellow_node_1", allowed_direction)
    if seg1:
        segments["annahme_segment_1"] = seg1

    seg2 = create_route_segment_by_names(node_manager, render, "annahme_segment_2",
                                         "yellow_node_1", "blue_node_2", allowed_direction)
    if seg2:
        segments["annahme_segment_2"] = seg2

    seg3 = create_route_segment_by_names(node_manager, render, "annahme_segment_3",
                                         "blue_node_2", "yellow_node_2", allowed_direction)
    if seg3:
        segments["annahme_segment_3"] = seg3

    seg4 = create_route_segment_by_names(node_manager, render, "annahme_segment_4",
                                         "yellow_node_2", "blue_node_3", allowed_direction)
    if seg4:
        segments["annahme_segment_4"] = seg4

    seg5 = create_route_segment_by_names(node_manager, render, "annahme_segment_5",
                                         "blue_node_3", "yellow_node_3", allowed_direction)
    if seg5:
        segments["annahme_segment_5"] = seg5

    seg6 = create_route_segment_by_names(node_manager, render, "annahme_segment_6",
                                         "yellow_node_3", "blue_node_4", allowed_direction)
    if seg6:
        segments["annahme_segment_6"] = seg6

    seg7 = create_route_segment_by_names(node_manager, render, "annahme_segment_7",
                                         "blue_node_4", "yellow_node_4", allowed_direction)
    if seg7:
        segments["annahme_segment_7"] = seg7

    seg8 = create_route_segment_by_names(node_manager, render, "annahme_segment_8",
                                         "yellow_node_4", "blue_node_5", allowed_direction)
    if seg8:
        segments["annahme_segment_8"] = seg8

    seg9 = create_route_segment_by_names(node_manager, render, "annahme_segment_9",
                                         "blue_node_5", "yellow_node_5", allowed_direction)
    if seg9:
        segments["annahme_segment_9"] = seg9

    seg10 = create_route_segment_by_names(node_manager, render, "annahme_segment_10",
                                          "yellow_node_5", "blue_node_6", allowed_direction)
    if seg10:
        segments["annahme_segment_10"] = seg10

    seg11 = create_route_segment_by_names(node_manager, render, "annahme_segment_11",
                                          "blue_node_6", "yellow_node_6", allowed_direction)
    if seg11:
        segments["annahme_segment_11"] = seg11

    seg12 = create_route_segment_by_names(node_manager, render, "annahme_segment_12",
                                          "yellow_node_6", "blue_node_7", allowed_direction)
    if seg12:
        segments["annahme_segment_12"] = seg12

    seg13 = create_route_segment_by_names(node_manager, render, "annahme_segment_13",
                                          "blue_node_7", "yellow_node_7", allowed_direction)
    if seg13:
        segments["annahme_segment_13"] = seg13

    seg14 = create_route_segment_by_names(node_manager, render, "annahme_segment_14",
                                          "yellow_node_7", "blue_node_8", allowed_direction)
    if seg14:
        segments["annahme_segment_14"] = seg14

    seg15 = create_route_segment_by_names(node_manager, render, "annahme_segment_15",
                                          "blue_node_8", "yellow_node_8", allowed_direction)
    if seg15:
        segments["annahme_segment_15"] = seg15

    seg16 = create_route_segment_by_names(node_manager, render, "annahme_segment_16",
                                          "yellow_node_8", "blue_node_9", allowed_direction)
    if seg16:
        segments["annahme_segment_16"] = seg16

    seg17 = create_route_segment_by_names(node_manager, render, "annahme_segment_17",
                                          "blue_node_9", "yellow_node_9", allowed_direction)
    if seg17:
        segments["annahme_segment_17"] = seg17

    seg18 = create_route_segment_by_names(node_manager, render, "annahme_segment_18",
                                          "yellow_node_9", "blue_node_10", allowed_direction)
    if seg18:
        segments["annahme_segment_18"] = seg18

    seg19 = create_route_segment_by_names(node_manager, render, "annahme_segment_19",
                                          "blue_node_10", "yellow_node_10", allowed_direction)
    if seg19:
        segments["annahme_segment_19"] = seg19

    seg20 = create_route_segment_by_names(node_manager, render, "annahme_segment_20",
                                          "yellow_node_10", "blue_node_22", allowed_direction)
    if seg20:
        segments["annahme_segment_20"] = seg20

    return segments



# ------------------------------
# 2. NavigationManager-Klasse
# ------------------------------

class NavigationManager:
    def __init__(self, node_manager, render):
        """
        Initialisierung des Navigation Managers.
        :param node_manager: Dein NodeManager, der alle Knoten verwaltet.
        :param render: Das Render-Objekt (wird gebraucht, um Positionen abzufragen).
        """
        self.node_manager = node_manager
        self.render = render
        # Erstelle den Graphen (RouteSegments) anhand deines bestehenden Routing-Codes.
        self.segments = define_garage_route_segments(self.node_manager, self.render)

    def calculate_route(self, start_node_name, end_node_name):
        """
        Berechnet eine Route als Liste von RouteSegment-Objekten von einem Start-Knoten zum Ziel-Knoten.
        Hier sollte später ein Pfadfindungsalgorithmus (z. B. Dijkstra oder A*) integriert werden.

        :param start_node_name: Name des Start-Knotens (z. B. "blue_node_3").
        :param end_node_name: Name des Ziel-Knotens (z. B. "blue_node_10").
        :return: Eine Liste von RouteSegment-Objekten, die den Weg darstellen.
        """
        # Platzhalter: Im Moment geben wir einfach alle Segmente in fester Reihenfolge zurück.
        route = []
        for name, segment in self.segments.items():
            route.append(segment)
        return route

    def segment_available(self, segment):
        """
        Prüft, ob ein Segment frei (nicht belegt) ist.
        :param segment: Das RouteSegment-Objekt.
        :return: True, wenn frei, sonst False.
        """
        return segment.is_free()

    def reserve_segment(self, segment, vehicle):
        """
        Reserviert ein Segment für ein Fahrzeug, sofern möglich.
        :param segment: Das RouteSegment.
        :param vehicle: Das Fahrzeug.
        :return: True, wenn Reservierung erfolgreich war, sonst False.
        """
        return segment.reserve(vehicle)

    def release_segment(self, segment):
        """
        Gibt ein zuvor reserviertes Segment wieder frei.
        :param segment: Das RouteSegment.
        """
        segment.release()


# ------------------------------
# 3. Dummy-Tester für den Routing- und Navigation Manager
# ------------------------------

if __name__ == '__main__':
    # Dummy NodeManager zum Testen
    from panda3d.core import NodePath


    class DummyNodeManager:
        def __init__(self):
            self.nodes = {}

        def register_node(self, name, pos):
            node = NodePath(name)
            node.setPos(pos)
            self.nodes[name] = node

        def get_node(self, name):
            return self.nodes.get(name)


    # Erstelle ein Dummy-Render-Objekt
    render_dummy = NodePath("render")
    dummy_manager = DummyNodeManager()

    # Registriere Dummy-Knoten für die benötigten Namen mit Beispielpositionen:
    dummy_manager.register_node("blue_node_21", Vec3(0, 0, 0))
    dummy_manager.register_node("yellow_node_21", Vec3(10, 0, 0))
    dummy_manager.register_node("blue_node_22", Vec3(0, 10, 0))
    dummy_manager.register_node("yellow_node_22", Vec3(10, 10, 0))
    dummy_manager.register_node("blue_node_23", Vec3(0, 20, 0))
    dummy_manager.register_node("yellow_node_23", Vec3(10, 20, 0))
    dummy_manager.register_node("blue_node_24", Vec3(0, 30, 0))
    dummy_manager.register_node("yellow_node_24", Vec3(10, 30, 0))
    dummy_manager.register_node("blue_node_25", Vec3(10, 40, 0))
    dummy_manager.register_node("yellow_node_25", Vec3(0, 40, 0))
    dummy_manager.register_node("blue_node_26", Vec3(0, 50, 0))
    dummy_manager.register_node("yellow_node_26", Vec3(10, 50, 0))
    dummy_manager.register_node("blue_node_27", Vec3(0, 60, 0))
    dummy_manager.register_node("yellow_node_27", Vec3(10, 60, 0))

    # Erstelle die RouteSegments
    segments = define_garage_route_segments(dummy_manager, render_dummy)
    print("Definierte RouteSegments:")
    for name, seg in segments.items():
        print(f"{name}: Start {seg.start}, Ende {seg.end}, Richtung {seg.allowed_direction}")


    # Test NavigationManager:
    class DummyVehicle:
        def __str__(self):
            return "DummyVehicle1"


    nav_manager = NavigationManager(dummy_manager, render_dummy)
    # Berechne eine Route (Platzhalter: alle Segmente in fester Reihenfolge)
    route = nav_manager.calculate_route("blue_node_22", "blue_node_27")
    print("\nBerechnete Route:")
    for seg in route:
        print(f"Segment: {seg.name} von {seg.start} nach {seg.end}, frei: {seg.is_free()}")

    # Beispiel: Reserviere das erste Segment für ein Fahrzeug und gebe es danach wieder frei.
    dummy_vehicle = DummyVehicle()
    if route:
        first_seg = route[0]
        if nav_manager.segment_available(first_seg):
            nav_manager.reserve_segment(first_seg, dummy_vehicle)
        print(f"\nNach Reservierung: Segment {first_seg.name} frei: {first_seg.is_free()}")
        # Freigabe des Segments
        nav_manager.release_segment(first_seg)
        print(f"Nach Freigabe: Segment {first_seg.name} frei: {first_seg.is_free()}")
