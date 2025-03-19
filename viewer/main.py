import json
import logging
import os
import re
import shutil

import gdown
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# from myapp.graph_creation.yml import get_cfg
from new_loader.ifc_to_neo4j import IfcToNeo4jConverter


class Project(BaseModel):
    name: str
    link: str


class ADCMProject(BaseModel):
    id: int
    name: str
    link: str


# cfg: dict = get_cfg("neo4j")
# TEST_IP = cfg.get("test_ip")
TEST_IP = '158.160.146.23'
LAST_API = '87.249.36.248:5013'


app = FastAPI()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
path_to_explorer = dict()


@app.post("/")
async def deploy_project(project: Project):
    os.chdir('/app/')
    url = f"{project.link[39:-12]}"
    logger.info(f'https://drive.google.com/drive/folders/{url}')
    gdown.download_folder(f'https://drive.google.com/drive/folders/{url}', quiet=True, use_cookies=False,
                          output=f'{project.name}')
    # os.system('ls')
    # os.system('wget --no-check-certificate \'https://docs.google.com/uc?export=download&id=FILEID\' -O FILENAME')
    os.chdir('./xeokit-bim-viewer-app/')
    os.system(f'node ./createProject.js -p {project.name} -s ../{project.name}/**/*.ifc')
    os.chdir('..')
    files = [f for f in os.listdir(f'./{project.name}')]
    for file in files:
        # print(f'./{project.name}/{file}')
        logger.info(f'./xeokit-bim-viewer-app/data/projects/{project.name}/models/{file[:-4]}/source/geometry.ifc')
        shutil.move(f'./{project.name}/{file}',
                    f'./xeokit-bim-viewer-app/data/projects/{project.name}/models/{file[:-4]}/source/geometry.ifc')

    neo4j_exp = IfcToNeo4jConverter()
    path = f'./xeokit-bim-viewer-app/data/projects/{project.name}/models/'
    neo4j_exp.create(path)
    path_to_explorer[path] = neo4j_exp
    return 200


@app.get("/load/{project_name}")
async def get_nodes(project_name: str):
    os.chdir('/app/')
    path = f'./{project_name}/'
    if path not in path_to_explorer:
        logger.error(f"{path} not in {path_to_explorer.keys()}")
        return JSONResponse(content={"message": "Нет ADCM в структуре файла"}, status_code=404)
        raise KeyError(f"{path} not in {path_to_explorer.keys()}")
    neo4j_exp = path_to_explorer.get(path)

    return JSONResponse(content=json.dumps(neo4j_exp.get_nodes()))
    # neo4j_exp.close()


@app.get("/links/{project_name}")
async def get_links(project_name: str):
    os.chdir('/app/')
    path = f'./{project_name}/'
    neo4j_exp = path_to_explorer.get(path)

    return JSONResponse(content=json.dumps(neo4j_exp.get_edges()))


@app.get("/copy/{project_id}/")
async def load_project(project_id: str, jwt: str):
    os.chdir('/app/')
    # jwt = request.headers.get('Authorization')
    jwt = f'Bearer {jwt}'
    # logger.info(f'jwt {jwt}')
    if os.path.isdir(f'./{project_id}'):
        shutil.rmtree(f'./{project_id}')
    if os.path.isdir(f'./xeokit-bim-viewer-app/data/projects/{project_id}/'):
        # shutil.rmtree(f'./xeokit-bim-viewer-app/data/projects/{project_id}/')
        os.chdir('./xeokit-bim-viewer-app/')
        os.system(f'node deleteProject.js -p {project_id}')
        os.chdir('/app/')

    os.mkdir(f'{project_id}')
    # download project
    os.chdir(f'./{project_id}/')

    # /api/Files/get_list_ifc_files_by_project/{ProjectId}
    headers = {"Authorization": f"{jwt}"}
    r = requests.get(f'http://{LAST_API}/api/Files/get_list_ifc_files_by_project/{project_id}', headers=headers)
    # print(r.json())
    for el in r.json()['ifcFiles']:
        m = requests.get(f"http://{LAST_API}/api/Files/download_file/{el['id']}/0", headers=headers, allow_redirects=True)
        open(f'{el["ifc_name"]}', 'wb').write(m.content)
    # r = requests.get(f'http://{TEST_IP}:8880/projects/info/{project_id}')
    # for el in r.json()['models']:
    #     new_url = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', TEST_IP, el['ifc'])
    #     m = requests.get(new_url, allow_redirects=True)
    #     open(f'{el["name"]}.ifc', 'wb').write(m.content)


    os.chdir('/app/')

    # os.chdir('./xeokit-bim-viewer-app/')
    # os.system(f'node ./createProject.js -p {project_id} -s ../{project_id}/**/*.ifc')
    # os.chdir('/app/')
    # files = [f for f in os.listdir(f'./{project_id}')]
    # for file in files:
    #     # print(f'./{project.name}/{file}')
    #     # print(f'./xeokit-bim-viewer-app/data/projects/{project.name}/models/{file[:-4]}/source/geometry.ifc')
    #     shutil.move(f'./{project_id}/{file}',
    #                 f'./xeokit-bim-viewer-app/data/projects/{project_id}/models/{file[:-4]}/source/geometry.ifc')

    neo4j_exp = IfcToNeo4jConverter()
    path = f'./{project_id}/'
    logger.info(path_to_explorer)
    neo4j_exp.create(path)
    path_to_explorer[path] = neo4j_exp
    return 200
