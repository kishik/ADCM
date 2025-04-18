import logging
import os

import ifcopenshell
import pandas as pd
from neo4j import GraphDatabase

from .data_collection import allNodes, calculateDistance

logger = logging.getLogger(__name__)

# Number of elements in storey for visualisation
LIMIT = 5

# ELEMENTS_URI = "neo4j://localhost:7686"
# GROUPS_URI = "neo4j://localhost:7685"
ELEMENTS_URI = "neo4j://neo4j_elements:7687"
GROUPS_URI = 'neo4j://neo4j_historical:7687'
USER = "neo4j"
PSWD = "23109900"

# The first hierarchial level (specific IFC type in this case)
WBS1 = "IfcBuildingStorey"

WBS2_LABEL = "WBS2"
WBS3_LABEL = "WBS3"


# WBS2 - other IFC types
def get_wbs2(element):
    return node_attributes(element).get("ADCM_RD")
    # return node_attributes(element).get("ADCM_RD") if node_attributes(element).get("ADCM_RD") is not None else 12345 


# WBS3 - GESN or DIN
def get_wbs3(element) -> str:
    atts = node_attributes(element)
    if "ADCM_GESN" in atts.keys():
        return atts.get("ADCM_GESN")
    if "ADCM_DIN" in atts.keys():
        return atts.get("ADCM_DIN")
    return "no GESN"


def node_attributes(elem) -> dict:
    atts = dict(
        global_id=str(elem.GlobalId),
        name=elem.Name,
        is_a=elem.is_a(),
        group_type=elem.Name.rpartition(":")[0],
    )

    def get_psets(element):
        psets = {}

        for definition in element.IsDefinedBy:
            # Проверяем, является ли это набором свойств
            if definition.is_a("IfcRelDefinesByProperties"):
                property_set = definition.RelatingPropertyDefinition
                if property_set.is_a("IfcPropertySet"):
                    pset_name = property_set.Name
                    psets[pset_name] = {}

                    for property_ in property_set.HasProperties:
                        if property_.is_a("IfcPropertySingleValue"):
                            prop_name = property_.Name
                            prop_value = property_.NominalValue.wrappedValue if property_.NominalValue else None
                            psets[pset_name][prop_name] = prop_value

        return psets

    psets = get_psets(elem)

    if "ADCM" in psets.keys():
        # delete unnecessary key "id" from ADCM
        if "id" in psets["ADCM"]:
            psets["ADCM"].pop('id')
        atts.update(psets["ADCM"])
    if "ADCM_GESN" in atts.keys():
        atts["ADCM_GESN"] = atts["ADCM_GESN"][:-3]
    atts.setdefault("ADCM_Title", None)
    atts.setdefault("ADCM_Level", None)
    atts.setdefault("ADCM_RD", None)
    atts.setdefault("ADCM_JobType", None)
    atts.setdefault("ADCM_Part", None)

    def get_coordinates(el) -> tuple[float, float, float]:
        if not hasattr(el, "ObjectPlacement"):
            return 0.0, 0.0, 0.0
        return tuple(round(i, 1) for i in list(el.ObjectPlacement.RelativePlacement.Location.Coordinates))

    atts["coordinates"] = get_coordinates(elem)
    atts.setdefault(
        "Elevation",
        round(elem.Elevation, 1) if hasattr(elem, "Elevation") else atts["coordinates"][2],
    )

    return atts


def get_all_children(element):
    all_children = set()

    # Используем связь element.ContainsElements
    if element.is_a('IfcSpatialStructureElement'):
        for rel in element.ContainsElements:
            # if rel.is_a("IfcRelContainedInSpatialStructure"):
            all_children.update(rel.RelatedElements)

    # Используем связь element.IsDecomposedBy
    if element.is_a('IfcObjectDefinition'):
        for rel in element.IsDecomposedBy:
            # if rel.is_a("IfcRelAggregates"):
            all_children.update(rel.RelatedObjects)

    return list(filter(lambda el: _filter_ifc(el), all_children))


def _filter_ifc(element) -> bool:
    return (
            element.is_a("IfcElement")
            or element.is_a("IfcSpatialStructureElement")
            or element.is_a("IfcObjectDefinition")
    ) and not (element.is_a("IfcGrid") or element.is_a("IfcAnnotation"))


def add_node(tx, id_, props_: dict):
    q = """
    CREATE (n:Element)
    SET n = $props
    SET n.id = $id
    """
    tx.run(q, id=str(id_), props=props_)  # , stor_id=str(stor_id_)


def add_contains_edge(tx, a_id, b_id):
    q_edge = '''
    MATCH (a:Element) WHERE a.id = $id1
    MATCH (b:Element) WHERE b.id = $id2
    MERGE (a)-[:CONTAINS]->(b)
    '''
    tx.run(q_edge, id1=str(a_id), id2=str(b_id))


def add_wbs_node(tx, parent_id, wbs_id, wbs_name, label):
    q_wbs_node = f'''
    MATCH (s) WHERE s.id = $s_id
    MERGE (s)-[:CONTAINS]->(:{label} {{id: $id, name: $name}})
    '''
    tx.run(q_wbs_node, s_id=str(parent_id), id=str(wbs_id), name=str(wbs_name))


def add_el_to_wbs(tx, wbs_id, element_id):
    q_wbs_el = '''
    MATCH (c) WHERE c.id = $cls_id
    MATCH (e) WHERE e.id = $el_id
    MERGE (c)-[:CONTAINS]->(e)
    '''
    tx.run(q_wbs_el, cls_id=str(wbs_id), el_id=str(element_id))


def link_classes(tx, id1: str, id2: str):
    q_link_classes = '''
    MATCH (a {id: $id1})
    MATCH (b {id: $id2})
    MERGE (a)-[r:FOLLOWS_IN_GROUP]->(b)
    '''
    tx.run(q_link_classes, id1=str(id1), id2=str(id2))


def traverse(tx, id1, id2):
    q_traverse = '''
    MATCH (a:Element) WHERE a.id = $id1
    MATCH (b:Element) WHERE b.id = $id2
    MERGE (a)-[:TRAVERSE_GROUP]->(b)
    '''
    tx.run(q_traverse, id1=str(id1), id2=str(id2))


class IfcToNeo4jConverter:
    def __init__(self):
        self.element_driver = GraphDatabase.driver(ELEMENTS_URI, auth=(USER, PSWD))
        self.element_driver.verify_connectivity()
        group_driver = GraphDatabase.driver(GROUPS_URI, auth=(USER, PSWD))
        group_driver.verify_connectivity()
        q_wbs2_rel = '''MATCH (a:IfcClass)-->(b:IfcClass)
            RETURN a.name AS type1, b.name AS type2'''
        self.wbs2_link_df = pd.DataFrame(group_driver.session().run(q_wbs2_rel).data())
        q_wbs3_rel = '''MATCH (a:WBS3)-->(b:WBS3)
            RETURN a.name AS type1, b.name AS type2'''
        self.wbs3_link_df = pd.DataFrame(group_driver.session().run(q_wbs3_rel).data())
        group_driver.close()

        df = pd.read_excel(
            "./new_loader/solution.xls",
            index_col=0,
            header=None,
            names=["GESN", "name"]
        ).dropna()
        self.gesn_to_name: dict = df.name.to_dict()

    def close(self):
        self.element_driver.close()

    def create(self, root: str):
        with self.element_driver.session() as session:
            session.run('MATCH (n) DETACH DELETE n')

            file_list = []
            for path, subdirs, files in os.walk(root):
                for name in files:
                    if name.endswith('.ifc'):
                        file_list.append(os.path.join(path, name))
            logger.info("ifc_to_neo4j.192", file_list)
            first_model = ifcopenshell.open(file_list[0])
            building = first_model.by_type("IfcBuilding")[0]
            session.execute_write(add_node, str(building.id()), node_attributes(building))

            for file_num, ifc_path in enumerate(file_list):
                def node(element):
                    return str(file_num) + '-' + str(element.id())

                model = ifcopenshell.open(ifc_path)
                storeys = model.by_type(WBS1)
                for stor in storeys:
                    atts = node_attributes(stor)
                    storey_name = atts.get("name")
                    # storey_elevation = round(atts.get("Elevation"), 1)
                    session.execute_write(add_node, node(stor), atts)
                    session.execute_write(add_contains_edge, str(building.id()), node(stor))

                    all_elements = get_all_children(stor)

                    wbs2_set = {get_wbs2(i) for i in all_elements}
                    wbs2_to_id = dict()

                    def insert_elements(group):
                        # add wbs2 node
                        session.execute_write(
                            add_wbs_node,
                            node(stor),
                            wbs2_to_id[group],
                            group,
                            WBS2_LABEL,
                        )

                        elements_in_wbs2 = set(filter(
                            lambda el: get_wbs2(el) == group,
                            all_elements
                        ))

                        wbs3_set = {get_wbs3(el) for el in elements_in_wbs2}
                        wbs3_to_id = dict()  # unique dict on each hierarchial level

                        for k, wbs3 in enumerate(wbs3_set):
                            wbs3_to_id[wbs3] = wbs2_to_id[group] + '-' + str(k)
                            # add wbs3 node
                            session.execute_write(
                                add_wbs_node,
                                wbs2_to_id[group],
                                wbs3_to_id[wbs3],
                                wbs3,
                                WBS3_LABEL,
                            )
                            # adding leaves of the graph (the work elements itself)
                            target_elems = list(filter(
                                lambda el: get_wbs3(el) == wbs3,
                                elements_in_wbs2
                            ))
                            target_elems.sort(key=lambda el: node_attributes(el).get("Elevation"))
                            for i in range(len(target_elems[:LIMIT])):
                                atts = node_attributes(target_elems[i])
                                atts.update({"storey_name": storey_name})
                                session.execute_write(add_node, node(target_elems[i]), atts)
                                session.execute_write(add_el_to_wbs, wbs3_to_id[wbs3], node(target_elems[i]))
                                if i != 0:
                                    session.execute_write(traverse, node(target_elems[i - 1]), node(target_elems[i]))

                        self.wbs3_link_df.apply(
                            lambda row: session.execute_write(
                                link_classes,
                                wbs3_to_id.get(row.type1),
                                wbs3_to_id.get(row.type2)
                            ),
                            axis=1,
                        )

                    for j, wbs2 in enumerate(wbs2_set):
                        wbs2_to_id[wbs2] = node(stor) + '-' + str(j)
                        insert_elements(wbs2)

                    self.wbs2_link_df.apply(
                        lambda row: session.execute_write(
                            link_classes,
                            wbs2_to_id.get(row.type1),
                            wbs2_to_id.get(row.type2)
                        ),
                        axis=1,
                    )

            q_storeys = '''
            MATCH (n) WHERE n.is_a = 'IfcBuildingStorey'
            RETURN n.id AS id, n.Elevation As elevation, n.name AS name'''
            level_df = pd.DataFrame(session.run(q_storeys).data())
            level_df.sort_values(by=['elevation'], inplace=True, ignore_index=True)

            def connect_wbs(parent_id_1, parent_id_2, label, rel_in_group, rel_type):
                q_get_last = f'''MATCH (p {{id: '{str(parent_id_1)}' }}) --> (s:{label})
                WHERE NOT (s)-[:{rel_in_group}]->(:{label})
                RETURN s.id AS id'''
                last_res = session.run(q_get_last).data()
                logger.info(290, last_res)
                q_get_first = f'''MATCH (p {{id: '{str(parent_id_2)}' }}) --> (s:{label})
                WHERE NOT (:{label})-[:{rel_in_group}]->(s)
                RETURN s.id AS id'''
                first_res = session.run(q_get_first).data()
                logger.info(295, first_res)
                for i in last_res:
                    for k in first_res:
                        q_rel = f'''MATCH (a:{label}) WHERE a.id = '{i['id']}'
                            MATCH (b:{label}) WHERE b.id = '{k['id']}'
                            MERGE (a)-[r:{rel_type}]->(b)
                            '''
                        session.run(q_rel)

            for ind, row in level_df.iterrows():
                if ind != 0:
                    # Connect WBS1 based on elevation
                    session.execute_write(link_classes, pred_id, row.id)
                    # Connect WBS2
                    connect_wbs(pred_id, row.id, WBS2_LABEL, "FOLLOWS_IN_GROUP", "FOLLOWS")
                pred_id = row.id

            q_get_neighbor_els = f'''
            MATCH (a:{WBS2_LABEL})-[:FOLLOWS_IN_GROUP|FOLLOWS]->(b:{WBS2_LABEL})
            RETURN a.id AS id1, b.id AS id2
            '''
            wbs2_df = pd.DataFrame(session.run(q_get_neighbor_els).data())
            wbs2_df.apply(
                lambda row: connect_wbs(row.id1, row.id2, WBS3_LABEL, "FOLLOWS_IN_GROUP", "FOLLOWS"),
                axis=1
            )

            q_get_neighbor_els = f'''
            MATCH (a:{WBS3_LABEL})-[:FOLLOWS_IN_GROUP|FOLLOWS]->(b:{WBS3_LABEL})
            RETURN a.id AS id1, b.id AS id2
            '''
            wbs3_df = pd.DataFrame(session.run(q_get_neighbor_els).data())
            wbs3_df.apply(
                lambda row: connect_wbs(row.id1, row.id2, "Element", "TRAVERSE_GROUP", "TRAVERSE"),
                axis=1
            )

    def get_nodes(self):
        q_storey_wbs2 = """MATCH 
        (el)-[:TRAVERSE|TRAVERSE_GROUP]->(fl) RETURN el.id as id, el.ADCM_Title as wbs1, el.storey_name as wbs2, 
        el.ADCM_RD as wbs3, el.ADCM_GESN as wbs4_id, el.name as name, el.is_a as ifc_type 
        UNION MATCH 
        (el)-[:TRAVERSE|TRAVERSE_GROUP]->(fl) RETURN fl.id as id, fl.ADCM_Title as wbs1, fl.storey_name as wbs2, 
        fl.ADCM_RD as wbs3, fl.ADCM_GESN as wbs4_id, fl.name as name, fl.is_a as ifc_type
        """
        with self.element_driver.session() as session:
            nodes = session.run(q_storey_wbs2).data()
            distances = calculateDistance(session, allNodes(session))
            for node in nodes:
                node.update({
                    "wbs4": self.gesn_to_name.get(node.get("wbs4_id")),
                    "distance": distances.get(node.get("id")),
                })
        nodes.sort(key=lambda el: el["distance"])
        return nodes

    def get_edges(self):
        query = """
        MATCH (el)-[:TRAVERSE|TRAVERSE_GROUP]->(flw) 
        RETURN el.id as source, flw.id as target
        """
        edges = self.element_driver.session().run(query).data()
        for edge in edges:
            edge.update({"type": "0", "lag": 0})
        return edges
