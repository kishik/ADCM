import logging
import os
import ifcopenshell
from ifccsv import IfcCsv
import pandas as pd
from neo4j import GraphDatabase


# URI examples: "neo4j://localhost", "neo4j+s://xxx.databases.neo4j.io"
URI = "neo4j://neo4j_elements:7687"
AUTH = ("neo4j", "23109900")


ELEMENTS_URI = "neo4j://neo4j_elements:7687"
USER = "neo4j"
PSWD = "23109900"

file = '0.ifc'
files = [file]

######## building
def create_wbs1(driver, name):
    summary = driver.execute_query("""
    CREATE (a:WBS1 {name: $name})
    """,
    name=name, database_="neo4j").summary


############# level
def wbs1_link_wbs2(driver, name2):
    summary = driver.execute_query("""
    MATCH (a:WBS1),(b:WBS2)
    WHERE a.name = b.WBS1 AND b.name = $name2
    CREATE (a)-[r:FOLLOWS_GROUP]->(b)
    """,
    name2=name2, database_="neo4j").summary


def create_wbs2(driver, name, WBS1):
    summary = driver.execute_query("""
    CREATE (a:WBS2 {name: $name, WBS1: $WBS1})
    """,
    name=name, WBS1=WBS1, database_="neo4j").summary
    wbs1_link_wbs2(driver, name)


############# GESN
def wbs2_link_wbs3(driver, GESN):
    summary = driver.execute_query("""
    MATCH (a:WBS2),(b:WBS3)
    WHERE b.name = $GESN AND a.name = b.WBS2 and a.WBS1 = b.WBS1
    CREATE (a)-[r:FOLLOWS_GROUP]->(b)
    """,
    GESN=GESN, database_="neo4j").summary


def create_wbs3(driver, GESN, WBS1, WBS2):
    summary = driver.execute_query("""
    CREATE (a:WBS3 {name: $GESN, WBS1: $WBS1, WBS2: $WBS2})
    """,
    GESN=GESN, WBS1=WBS1, WBS2=WBS2, database_="neo4j").summary
    wbs2_link_wbs3(driver, GESN)


################################### element
def wbs3_link_element(driver, GlobalId):
    summary = driver.execute_query("""
    MATCH (a:WBS3),(b:ELEMENT)
    WHERE a.name = b.GESN AND b.GlobalId = $GlobalId and a.WBS1 = b.WBS1 and a.WBS2 = b.WBS2
    CREATE (a)-[r:FOLLOWS_GROUP]->(b)
    """,
    GlobalId=GlobalId, database_="neo4j").summary

# GlobalId уникальный ID работы
def create_element(driver, name, GlobalId, JOBTYPE, WBS1, WBS2, GESN):
    summary = driver.execute_query("""
    CREATE (a:ELEMENT {name: $name, GlobalId: $GlobalId, JOBTYPE: $JOBTYPE, GESN: $GESN, WBS1: $WBS1, WBS2: $WBS2})
    """,
    name=name, GlobalId=GlobalId, JOBTYPE=JOBTYPE, GESN=GESN, WBS1=WBS1, WBS2=WBS2, database_="neo4j").summary
    wbs3_link_element(driver, GlobalId)




def prepare_df(file):
    model = ifcopenshell.open(file)
    elements = ifcopenshell.util.selector.filter_elements(model, "IfcElement")
    attributes = ["id",'Текст', "Name", 'IfcBuildingStorey']
    ifc_csv = IfcCsv()
    ifc_csv.export(model, elements, attributes, output=f"{file[:-4]}.csv", format="csv", delimiter=",", null="-")
    df = ifc_csv.export_pd()
    df = pd.merge(df[['GlobalId', 'Name']], pd.json_normalize(df['Текст']), left_index=True, right_index=True)
    return df.dropna()

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    driver.verify_connectivity()
    summary = driver.execute_query("""
    MATCH (n) DETACH DELETE n
    """,
    database_="neo4j").summary
    df = prepare_df(file)
    # сейчас только одно здание
    # if len(files) > 1:
    #     for i in range(len(files)):
    #         df = pd.concat([df, prepare_df(files[i + 1])], ignore_index=True)

    create_wbs1(driver, df['ADCM_Title'][0])

    for lvl in list(df['ADCM_Level'].unique()):

        create_wbs2(driver, lvl, df['ADCM_Title'][0])

        for sublvl in list(df[df['ADCM_Level']==lvl]['ADCM_GESN'].unique()):
            create_wbs3(driver, sublvl, df['ADCM_Title'][0], lvl)

            sub_df = df[(df['ADCM_Level']==lvl) & (df['ADCM_GESN']==sublvl)]

            for index, row in sub_df.iterrows():
                create_element(driver, row['Name'], row['GlobalId'], row['ADCM_JobType'], df['ADCM_Title'][0], lvl, sublvl)


################

def allNodes(session):
    """
    Возвращает все ноды
    :return: список нодов
    """

    q_data_obtain = '''MATCH (n:Element) 
    WHERE NOT n.is_a IN ["IfcBuilding", "IfcBuildingStorey"]
    RETURN DISTINCT n.id AS din'''
    result = session.run(q_data_obtain).data()
    return np.array([item["din"] for item in result])


def parentsByDin(din, session):
    """
    Возвращает всех родителей элемента din
    :param din:
    :param session:
    :return: np.array массив DINов родителей элемента
    """

    q_data_obtain = """
    MATCH (c)-[r:TRAVERSE|TRAVERSE_GROUP]->(a)
    WHERE a.id = $din
    RETURN DISTINCT c.id AS din
    """
    result = session.run(q_data_obtain, din=din).data()
    dins_arr = np.array([item["din"] for item in result])
    dins_arr = dins_arr[~np.isin(dins_arr, din)]
    return dins_arr


def childrenByDin(din, session):
    """
    Возвращает всех детей элемента din
    :param din:
    :param session:
    :return: list динов
    """
    q_data_obtain = """
    MATCH (a)-[r:TRAVERSE|TRAVERSE_GROUP]->(c)
    WHERE a.id = $din
    RETURN DISTINCT c.id AS din
    """
    result = session.run(q_data_obtain, din=din).data()
    children_arr = np.array([item["din"] for item in result])
    children_arr = children_arr[~np.isin(children_arr, din)]
    return children_arr


def prohod(start_din, distances, session, dins, cur_level=0, visited=[]):
    """
    Проходит рекурсивный путь по своим детям, указывая максимальную глубину рекурсии,
    сравнивая текущую и полученную сейчас
    """
    if start_din in visited:
        return
    visited.append(start_din)
    if start_din not in dins:
        for element in childrenByDin(start_din, session):
            prohod(element, distances, session, dins, cur_level, visited)
    else:
        if start_din not in distances:
            distances[start_din] = 0

        distances[start_din] = max(cur_level, distances[start_din])

        for element in childrenByDin(start_din, session):
            if start_din == element:
                continue
            # раньше здесь был get_edge_type, но сейчас у нас всегда тип связи "FS"
            prohod(element, distances, session, dins, cur_level + 1, visited.copy())


def calculateDistance(session, dins):
    """
    Запускает проход по всем нодам, не имеющим родителей
    dins это дины которые нас интересуют в рамках одного отчета
    :return: dict нодов с их глубиной в графе
    """
    distances = {}
    for node in allNodes(session):
        if parentsByDin(node, session).size > 0:
            continue
        prohod(start_din=node, distances=distances, session=session, cur_level=0, dins=dins, visited=list())
    return distances
