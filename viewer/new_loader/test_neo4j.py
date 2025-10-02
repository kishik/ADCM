import logging
import os
import pandas as pd
from neo4j import GraphDatabase
from ifccsv import IfcCsv
import ifcopenshell
import numpy as np

# URI examples: "neo4j://localhost", "neo4j+s://xxx.databases.neo4j.io"
# URI = "neo4j://localhost"
URI = "neo4j://neo4j_user:7687"
AUTH = ("neo4j", "23109900")

HISTURI = "neo4j://neo4j_historical:7687"

######## building
def create_wbs1(driver, name):
    summary = driver.execute_query("""
    CREATE (a:WBS1 {name: $name})
    """,
    name=name, database_="neo4j").summary


############# level
def wbs1_link_wbs2(driver, name2, prid):
    summary = driver.execute_query("""
    MATCH (a:WBS1),(b:WBS2)
    WHERE a.name = b.WBS1 AND b.name = $name2 and ID(b) = $prid
    CREATE (a)-[r:FOLLOWS_GROUP]->(b)
    """,
    name2=name2, prid=prid, database_="neo4j").summary


def create_wbs2(driver, name, WBS1):
    records, summary, keys = driver.execute_query("""
    CREATE (a:WBS2 {name: $name, WBS1: $WBS1})
                                   RETURN ID(a) AS info
    """,
    name=name, WBS1=WBS1, database_="neo4j")
    wbs1_link_wbs2(driver, name, records[0].data()['info'])


############# GESN
def wbs2_link_wbs3(driver, GESN, prid):
    summary = driver.execute_query("""
    MATCH (a:WBS2),(b:WBS3)
    WHERE b.name = $GESN AND a.name = b.WBS2 and a.WBS1 = b.WBS1 and ID(b) = $prid
    CREATE (a)-[r:FOLLOWS_GROUP]->(b)
    """,
    GESN=GESN, prid=prid, database_="neo4j")


def create_wbs3(driver, GESN, WBS1, WBS2):
    records, summary, keys = driver.execute_query("""
    CREATE (a:WBS3 {name: $GESN, WBS1: $WBS1, WBS2: $WBS2})
                                   RETURN ID(a) AS info
    """,
    GESN=GESN, WBS1=WBS1, WBS2=WBS2, database_="neo4j")
    wbs2_link_wbs3(driver, GESN, records[0].data()['info'])


################################### element
def wbs3_link_element(driver, GlobalId):
    summary = driver.execute_query("""
    MATCH (a:WBS3),(b:ELEMENT)
    WHERE a.name = b.GESN AND b.GlobalId = $GlobalId and a.WBS1 = b.WBS1 and a.WBS2 = b.WBS2
    CREATE (a)-[r:INSIDE]->(b)
    """,
    GlobalId=GlobalId, database_="neo4j").summary

# GlobalId уникальный ID работы
def create_element(driver, name, GlobalId, JOBTYPE, WBS1, WBS2, GESN, flag):
    summary = driver.execute_query("""
    CREATE (a:ELEMENT {name: $name, GlobalId: $GlobalId, JOBTYPE: $JOBTYPE, GESN: $GESN, WBS1: $WBS1, WBS2: $WBS2})
    """,
    name=name, GlobalId=GlobalId, JOBTYPE=JOBTYPE, GESN=GESN, WBS1=WBS1, WBS2=WBS2, database_="neo4j").summary
    if flag:
        wbs3_link_element(driver, GlobalId)


def link_levels(driver, oldlvl, newlvl):
    summary = driver.execute_query("""
    MATCH (a:WBS2),(b:WBS2)
    WHERE a.name = $oldlvl AND b.name = $newlvl 
    CREATE (a)-[r:LEVELCONNECTION]->(b)
    """,
    oldlvl=oldlvl, newlvl=newlvl, database_="neo4j").summary


def link_elements(driver, oldGlobalId, newGlobalId):
    summary = driver.execute_query("""
    MATCH (a:ELEMENT),(b:ELEMENT)
    WHERE a.GlobalId = $oldGlobalId AND b.GlobalId = $newGlobalId 
    CREATE (a)-[r:LINE]->(b)
    """,
    oldGlobalId=oldGlobalId, newGlobalId=newGlobalId, database_="neo4j").summary


def link_gesn_same_level(driver, linked, levels, first_elem_lvl_gesn, last_elem_lvl_gesn):
    # [(1,2), (3,2), (1,3)] пример соединений ГЕСН
    for link in linked:
        driver.execute_query("""
        MATCH (a:WBS3),(b:WBS3)
        WHERE a.name = $oldGESN AND b.name = $newGESN and a.WBS1 = b.WBS1 and a.WBS2 = b.WBS2
        CREATE (a)-[r:GESNCONNECTED]->(b)
        """,
        oldGESN=link[0], newGESN=link[1], database_="neo4j")
    # соединяем последний элемент из раннего ГЭСН и первый элемент из позднего
    for lvl in levels:
        for link in linked:
            # print(link)
            # print(first_elem_lvl_gesn)
            driver.execute_query("""
            MATCH (a:ELEMENT),(b:ELEMENT)
            WHERE a.GlobalId = $oldID AND b.GlobalId = $newID
            CREATE (a)-[r:LINE]->(b)
            """,
            
            oldID=last_elem_lvl_gesn[lvl][link[0]], newID=first_elem_lvl_gesn[lvl][link[1]], database_="neo4j")


def link_gesn_different_level(driver, linked, levels, first_elem_lvl_gesn, last_elem_lvl_gesn):
    for link in linked:
        for i in range(len(levels) - 1):
            driver.execute_query("""
        MATCH (a:WBS3),(b:WBS3)
        WHERE a.name = $oldGESN AND b.name = $newGESN and a.WBS2 = $oldLevel and b.WBS2 = $newLevel
        CREATE (a)-[r:GESNCONNECTED]->(b)
        """,
        oldGESN=link[0], newGESN=link[1], oldLevel=levels[i], newLevel=levels[i+1], database_="neo4j")
            driver.execute_query("""
            MATCH (a:ELEMENT),(b:ELEMENT)
            WHERE a.GlobalId = $oldID AND b.GlobalId = $newID
            CREATE (a)-[r:LINE]->(b)
            """,
            
            oldID=last_elem_lvl_gesn[levels[i]][link[0]], newID=first_elem_lvl_gesn[levels[i+1]][link[1]], database_="neo4j")

##########
def link_same_gesn_different_level(driver, levels, first_elem_lvl_gesn, last_elem_lvl_gesn, df):
    for i in range(len(levels) - 1):
        driver.execute_query("""
            MATCH (a:WBS3),(b:WBS3)
            WHERE a.name = b.name and a.WBS2 = $oldLevel and b.WBS2 = $newLevel
            CREATE (a)-[r:GESNCONNECTED]->(b)
            """,
            oldLevel=levels[i], newLevel=levels[i+1], database_="neo4j")
        
    for i in range(len(levels) - 1):
        for GESN in list(df[df['ADCM_Level']==levels[i]]['ADCM_GESN'].unique()):
            driver.execute_query("""
            MATCH (a:ELEMENT),(b:ELEMENT)
            WHERE a.GlobalId = $oldID AND b.GlobalId = $newID
            CREATE (a)-[r:LINE]->(b)
            """,
            
            oldID=last_elem_lvl_gesn[levels[i]][GESN], newID=first_elem_lvl_gesn[levels[i+1]][GESN], database_="neo4j")


def prepare_df(file):
    file=file[0]
    print(file)
    model = ifcopenshell.open(file)
    elements = ifcopenshell.util.selector.filter_elements(model, "IfcElement")
    attributes = ["id",'Текст', "Name", 'IfcBuildingStorey']
    ifc_csv = IfcCsv()
    ifc_csv.export(model, elements, attributes, output=f"{file[:-4]}.csv", format="csv", delimiter=",", null="-")
    df = ifc_csv.export_pd()
    df = pd.merge(df[['GlobalId', 'Name']], pd.json_normalize(df['Текст']), left_index=True, right_index=True)
    return df.dropna()


def get_hist_links():
    with GraphDatabase.driver(HISTURI, auth=AUTH) as driver2:
        records, summary, keys = driver2.execute_query("""
        MATCH (a:Work)-[r:FOLLOWS]->(c:Work)

        RETURN a.DIN as source, c.DIN as target
        """,
        database_="neo4j")
        # children_arr = np.array([item.data()["din"] for item in records])
        # print(records)
        
        edges = [(record.data()['source'], record.data()['target']) for record in records]
        return edges


def allNodes(driver):
    """
    Возвращает все ноды
    :return: список нодов
    """
    records, summary, keys = driver.execute_query("""
    MATCH (n1:ELEMENT) RETURN ID(n1) as din
    """,
    database_="neo4j")
    
    return np.array([item.data()["din"] for item in records])


def allNodesGESN(driver):
    """
    Возвращает все ноды
    :return: список нодов
    """
    records, summary, keys = driver.execute_query("""
    MATCH (n1:WBS3) RETURN n1.name as din
    """,
    database_="neo4j")
    
    return np.array([item.data()["din"] for item in records])


def parentsByDin(driver, din):
    """
    Возвращает всех родителей элемента din
    :param din:
    :param session:
    :return: np.array массив DINов родителей элемента
    """

    records, summary, keys = driver.execute_query("""
    MATCH (c)-[r:LINE]->(a)
    WHERE ID(a) = $din
    RETURN ID(c) AS din
    """,
    din=din, database_="neo4j")
    dins_arr = np.array([item.data()["din"] for item in records])
    # dins_arr = dins_arr[~np.isin(dins_arr, din)]
    return dins_arr


def childrenByDin(driver, din):
    """
    Возвращает всех детей элемента din
    :param din:
    :param session:
    :return: list динов
    """
    records, summary, keys = driver.execute_query("""
    MATCH (a)-[r:LINE]->(c)
    WHERE ID(a) = $din
    RETURN ID(c) AS din
    """,
    din=din, database_="neo4j")
    children_arr = np.array([item.data()["din"] for item in records])
    # children_arr = children_arr[~np.isin(children_arr, din)]
    return children_arr


def prohod(start_din, distances, driver, dins, cur_level=0, visited=[]):
    """
    Проходит рекурсивный путь по своим детям, указывая максимальную глубину рекурсии,
    сравнивая текущую и полученную сейчас
    """
    if start_din in visited:
        return
    visited.append(start_din)
    if start_din not in dins:
        for element in childrenByDin(driver, start_din):
            prohod(element, distances, driver, dins, cur_level, visited)
    else:
        if start_din not in distances:
            distances[start_din] = 0

        distances[start_din] = max(cur_level, distances[start_din])

        for element in childrenByDin(driver, start_din):
            if start_din == element:
                continue
            # раньше здесь был get_edge_type, но сейчас у нас всегда тип связи "FS"
            prohod(element, distances, driver, dins, cur_level + 1, visited.copy())


def calculateDistance(driver, dins):
    """
    Запускает проход по всем нодам, не имеющим родителей
    dins это дины которые нас интересуют в рамках одного отчета
    :return: dict нодов с их глубиной в графе
    """
    distances = {}
    for node in allNodes(driver):
        if parentsByDin(driver, node).size > 0:
            continue
        prohod(start_din=node, distances=distances, driver=driver, cur_level=0, dins=dins, visited=list())
    return distances


def get_nodes(driver):
        records, summary, keys = driver.execute_query("""
        MATCH (el:ELEMENT) RETURN ID(el) as id, el.WBS1 as wbs1, el.WBS2 as wbs2, 
        el.GESN as wbs3, el.JOBTYPE as wbs4_id, el.JOBTYPE as wbs4, el.name as name
    """,
    database_="neo4j")
        nodes = [record.data() for record in records]
        distances = calculateDistance(driver, allNodes(driver))
        for node in nodes:
            node.update({
                "distance": distances.get(node.get("id")),
            })
        nodes.sort(key=lambda el: el["distance"])
        return nodes


def get_edges(driver):

    records, summary, keys = driver.execute_query("""
    MATCH (a)-[r:LINE]->(c)

    RETURN ID(a) as source, ID(c) as target
    """,
    database_="neo4j")
    # children_arr = np.array([item.data()["din"] for item in records])
    # print(records)
    
    edges = [record.data() for record in records]
    # print(edges)
    # edges = self.element_driver.session().run(query).data()
    for edge in edges:
        edge.update({"type": "0", "lag": 0})
    print(get_hist_links())
    print(allNodesGESN(driver))
    return edges


def get_nodes_big(files):
    # file = '0.ifc'
    # files = [file]
    print(files)
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        first_elem_lvl_gesn = {}
        last_elem_lvl_gesn = {}
        driver.verify_connectivity()
        driver.execute_query("""
        MATCH (n) DETACH DELETE n
        """,
        database_="neo4j")
        df = prepare_df(files[0])
        if len(files) > 1:
            for i in range(len(files) - 1):
                df = pd.concat([df, prepare_df(files[i + 1])], ignore_index=True)

        create_wbs1(driver, df['ADCM_Title'][0])
        lvlprev = None
        for lvl in sorted(list(df['ADCM_Level'].unique())):
            first_elem_lvl_gesn[lvl] = {}
            last_elem_lvl_gesn[lvl] = {}
            create_wbs2(driver, lvl, df['ADCM_Title'][0])
            if lvlprev is not None:
                link_levels(driver, lvlprev, lvl)
            lvlprev = lvl
            for sublvl in list(df[df['ADCM_Level']==lvl]['ADCM_GESN'].unique()):
                create_wbs3(driver, sublvl, df['ADCM_Title'][0], lvl)

                sub_df = df[(df['ADCM_Level']==lvl) & (df['ADCM_GESN']==sublvl)]
                elprev = None
                for index, row in sub_df.iterrows():
                    if elprev is None:
                        create_element(driver, row['Name'], row['GlobalId'], row['ADCM_JobType'], df['ADCM_Title'][0], lvl, sublvl, True)
                        first_elem_lvl_gesn[lvl][sublvl] = row['GlobalId']
                    if elprev is not None:
                        create_element(driver, row['Name'], row['GlobalId'], row['ADCM_JobType'], df['ADCM_Title'][0], lvl, sublvl, False)
                        link_elements(driver, elprev, row['GlobalId'])
                    last_elem_lvl_gesn[lvl][sublvl] = row['GlobalId']
                    elprev = row['GlobalId']
        driver.execute_query("""
        MATCH (n:WBS1) DETACH DELETE n
        """,
        database_="neo4j")
        # [(1,2), (3,2), (1,3)] пример соединений ГЕСН
        Nodes = allNodesGESN(driver)
        filtered = []
        for el in get_hist_links():
            if el[0] in Nodes and el[1] in Nodes:
                filtered.append(el)
        link_gesn_same_level(driver, filtered, 
                            sorted(list(df['ADCM_Level'].unique())), first_elem_lvl_gesn, last_elem_lvl_gesn)
        link_gesn_different_level(driver, filtered,
                                sorted(list(df['ADCM_Level'].unique())), first_elem_lvl_gesn, last_elem_lvl_gesn)
        link_same_gesn_different_level(driver, sorted(list(df['ADCM_Level'].unique())), first_elem_lvl_gesn, last_elem_lvl_gesn, df)
        # добавить на след этаж аналогично lvl[link1] < lvl[link2] <=?
        # должна ли быть связь между этажами одинакового класса?
        # класс со следующего этажа после класса на этом
        driver.execute_query("""
        MATCH (n:WBS2) DETACH DELETE n
        """,
        database_="neo4j")
        driver.execute_query("""
        MATCH (n:WBS3) DETACH DELETE n
        """,
        database_="neo4j")
        return get_nodes(driver)
    

def get_edges_big(files):
    # file = '0.ifc'
    # files = [file]
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        # first_elem_lvl_gesn = {}
        # last_elem_lvl_gesn = {}
        # driver.verify_connectivity()
        # driver.execute_query("""
        # MATCH (n) DETACH DELETE n
        # """,
        # database_="neo4j")
        # df = prepare_df([files[0]])
        # if len(files) > 1:
        #     for i in range(len(files) - 1):
        #         df = pd.concat([df, prepare_df([files[i + 1]])], ignore_index=True)

        # create_wbs1(driver, df['ADCM_Title'][0])
        # lvlprev = None
        # for lvl in sorted(list(df['ADCM_Level'].unique())):
        #     first_elem_lvl_gesn[lvl] = {}
        #     last_elem_lvl_gesn[lvl] = {}
        #     create_wbs2(driver, lvl, df['ADCM_Title'][0])
        #     if lvlprev is not None:
        #         link_levels(driver, lvlprev, lvl)
        #     lvlprev = lvl
        #     for sublvl in list(df[df['ADCM_Level']==lvl]['ADCM_GESN'].unique()):
        #         create_wbs3(driver, sublvl, df['ADCM_Title'][0], lvl)

        #         sub_df = df[(df['ADCM_Level']==lvl) & (df['ADCM_GESN']==sublvl)]
        #         elprev = None
        #         for index, row in sub_df.iterrows():
        #             if elprev is None:
        #                 create_element(driver, row['Name'], row['GlobalId'], row['ADCM_JobType'], df['ADCM_Title'][0], lvl, sublvl, True)
        #                 first_elem_lvl_gesn[lvl][sublvl] = row['GlobalId']
        #             if elprev is not None:
        #                 create_element(driver, row['Name'], row['GlobalId'], row['ADCM_JobType'], df['ADCM_Title'][0], lvl, sublvl, False)
        #                 link_elements(driver, elprev, row['GlobalId'])
        #             last_elem_lvl_gesn[lvl][sublvl] = row['GlobalId']
        #             elprev = row['GlobalId']
        # driver.execute_query("""
        # MATCH (n:WBS1) DETACH DELETE n
        # """,
        # database_="neo4j")

        # # [(1,2), (3,2), (1,3)] пример соединений ГЕСН
        # # link_gesn_same_level(driver, [], 
        # #                     sorted(list(df['ADCM_Level'].unique())), first_elem_lvl_gesn, last_elem_lvl_gesn)
        # # link_gesn_different_level(driver, [],
        # #                         sorted(list(df['ADCM_Level'].unique())), first_elem_lvl_gesn, last_elem_lvl_gesn)
        # link_same_gesn_different_level(driver, sorted(list(df['ADCM_Level'].unique())), first_elem_lvl_gesn, last_elem_lvl_gesn, df)
        # # добавить на след этаж аналогично lvl[link1] < lvl[link2] <=?
        # # должна ли быть связь между этажами одинакового класса?
        # # класс со следующего этажа после класса на этом
        # driver.execute_query("""
        # MATCH (n:WBS2) DETACH DELETE n
        # """,
        # database_="neo4j")
        # driver.execute_query("""
        # MATCH (n:WBS3) DETACH DELETE n
        # """,
        # database_="neo4j")
        return get_edges(driver)


    # print(allNodes(driver))
    # print(parentsByDin(driver, 270))
    # print(childrenByDin(driver, 269))
    # distances = {}
    # prohod(371, distances, driver, allNodes(driver), cur_level=0, visited=[])
    # print(distances)
    # print(calculateDistance(driver, allNodes(driver)))
    # print(get_nodes(driver))
##################

