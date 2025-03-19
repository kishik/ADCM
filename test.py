import requests
import os
import shutil
from viewer.new_loader.ifc_to_neo4j import IfcToNeo4jConverter

LAST_API = '87.249.36.248:5013'

project_id = '2691866f-a504-4972-bebd-c9058f3b2b50'
headers = {"Authorization": f"Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjdXJyZW50VGltZSI6IjIwMjUtMDEtMjlUMDU6Mjg6MjkuOTk2WiIsInJhbmRvbU51bWJlciI6IjQ2NzkiLCJleHAiOjE3MzgxMzkzMDksImlzcyI6IllvdXJJc3N1ZXIiLCJhdWQiOiJZb3VyQXVkaWVuY2UifQ.HqRI4ItP3G_GB6wcNDOdHu0sDkf6pvx5JhzmHo1iFFg"}
# os.chdir('/app/')
# jwt = request.headers.get('Authorization')
jwt = f'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjdXJyZW50VGltZSI6IjIwMjUtMDEtMzFUMDg6Mjg6NTguODU1WiIsInJhbmRvbU51bWJlciI6IjgwODAiLCJleHAiOjE3MzgzMjI5MzgsImlzcyI6IllvdXJJc3N1ZXIiLCJhdWQiOiJZb3VyQXVkaWVuY2UifQ.p4r006cKqxlqfXncAb_A-j6t2rJDyGUnPcBRdYx42ls'
# logger.info(f'jwt {jwt}')
if os.path.isdir(f'./{project_id}'):
        shutil.rmtree(f'./{project_id}')
# if os.path.isdir(f'./xeokit-bim-viewer-app/data/projects/{project_id}/'):
# shutil.rmtree(f'./xeokit-bim-viewer-app/data/projects/{project_id}/')
# os.chdir('./xeokit-bim-viewer-app/')
# os.system(f'node deleteProject.js -p {project_id}')
# os.chdir('/app/')

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


# os.chdir('/app/')

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
# logger.info(path_to_explorer)
neo4j_exp.create(path)
# path_to_explorer[path] = neo4j_exp