import json
import logging
import re
from datetime import datetime, timedelta

import pandas as pd
import requests
from django.http import HttpResponseNotFound, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.edit import FormView
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from myapp.forms import AddLink, AddNode, UploadFileForm
from myapp.graph_creation import yml
from myapp.models import ActiveLink, Link, Project, Task2
from myapp.serializers import LinkSerializer, TaskSerializer
from .forms import FileFieldForm
from .gantt import data_collect, net_hierarhy
from .graph_creation import add, neo4jexplorer
from yandex_cloud_ml_sdk import YCloudML


logger = logging.getLogger(__name__)
cfg: dict = yml.get_cfg("neo4j")

URL = cfg.get("url")
USER = cfg.get("user")
PASS = cfg.get("password")

X2_URL = cfg.get("x2_url")
X2_PASS = cfg.get("x2_password")
JS_URL = cfg.get("js_url")
JS_PASS = cfg.get("js_pass")
VIEWER_URL = cfg.get("viewer")
IP = cfg.get("white_ip")
API_ADDRESS = cfg.get("api_address")
API_DB_URL = cfg.get("api_db_url")
API_DB = cfg.get("api_db")
API_LOGIN = cfg.get("api_login")
API_PASSWORD = cfg.get("api_password")
GPT_FOLDER = cfg.get("gpt_folder")
GPT_KEY = cfg.get("gpt_key")

sdk = YCloudML(
    folder_id=GPT_FOLDER,
    auth=GPT_KEY,
)

model = sdk.models.completions("yandexgpt")
model = model.configure(temperature=0.1)


graph_data = []
df = pd.DataFrame()
dates = dict()


def login(request):
    if not request.user.is_authenticated:
        return redirect("/login/")
    if not request.user.is_authenticated:
        return render(request, "registration/login.html")


def work_in_progress(request):
    """
    Заглушка
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    return render(request, "myapp/building.html")


def new_graph(request):
    """
    Показ исторического графа
    :param request:
    :return:
    """
    logger.debug(f'Show Historical Graph...')
    if not request.user.is_authenticated:
        return redirect("/login/")
    context = {
        "form": UploadFileForm(),
        "url": JS_URL,
        "user_graph": USER,
        "pass": PASS,
        "link": AddLink(),
        "node": AddNode(),
        "ip": f'neo4j://{IP}:7688'
    }
    return render(request, "myapp/hist_graph.html", context)


def projects(request):
    """
    Выводит проекты
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    projects = Project.objects.all()

    project = ActiveLink.objects.filter(userId=request.user.id).last()
    if not project:
        project = ActiveLink()
        project.projectId = None
        project.modelId = None

    form = FileFieldForm()
    return render(request, "myapp/projects.html",
                  {"projects": projects, "project": project.projectId, "form": form, 'link': VIEWER_URL})


def adcm_projects(request):
    """
    Выводит проекты
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    # projects = Project.objects.all()

    # project = ActiveLink.objects.filter(userId=request.user.id).last()
    # if not project:
    #     project = ActiveLink()
    #     project.projectId = None
    #     project.modelId = None

    # form = FileFieldForm()
    jwt_request = requests.post(''.join([API_ADDRESS, '/api/fetch/connect']), 
                             json={
                                 "url": API_DB_URL,
                                 "db": API_DB,
                                 "login": API_LOGIN,
                                 "password": API_PASSWORD
                                 })
# print(jwt_request.status_code)                                 
    jwt = jwt_request.text
    headers = {"Authorization": f"Bearer {jwt}"}
    response = requests.get(''.join([API_ADDRESS, '/api/projects']), headers=headers)
    projects = []
    for el in response.json():
        projects.append({'id': el['id'], 'name': el['text']})
    # print(projects)
    return render(request, "myapp/adcm_projects.html", {"projects": projects, 'link': VIEWER_URL})


def project_download(request, project_id):
    # api call to download
    response = requests.post(f'http://viewer:8070/copy/{project_id}')
    # volumes
    return HttpResponseRedirect(f"/volumes/{project_id}")


def project_create(request):
    """
    Создание project
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    if request.method == "POST":
        project = Project()
        project.name = request.POST.get("name")
        project.link = request.POST.get("link")
        project.isActive = True
        project.userId = request.user.id
        project.save()
        post_data = {'name': project.name, 'link': project.link}
        logger.info(post_data)
        response = requests.post('http://viewer:8070/', json=post_data)
        content = response.content
    return HttpResponseRedirect("/projects/")


def project_edit(request, id):
    """
    Изменение project
    :param request:
    :param id:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    try:
        project = Project.objects.get(id=id)
        if project.userId != request.user.id:
            return HttpResponseNotFound("<h2>It's not your project</h2>")
        if request.method == "POST":
            project.name = request.POST.get("name")
            project.link = request.POST.get("link")
            project.save()
            return HttpResponseRedirect("/projects/")
        else:
            return render(request, "myapp/project_edit.html", {"project": project})
    except project.DoesNotExist:
        return HttpResponseNotFound("<h2>project not found</h2>")


def project_delete(request, id):
    """
    Удаление URN
    :param request:
    :param id:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    try:
        project = Project.objects.get(id=id)
        if project.userId != request.user.id:
            return HttpResponseNotFound("<h2>Это не ваш проект</h2>")
        project.delete()
        return HttpResponseRedirect("/projects/")
    except project.DoesNotExist:
        return HttpResponseNotFound("<h2>Проект не найден</h2>")


@csrf_exempt
def upload(request):
    """
    Загрузка графа в виде файла в исторический граф
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")

    if request.method == "POST":
        session = data_collect.authentication(url=X2_URL, user=USER, password=X2_PASS)
        add.from_one_file(session, request.FILES["file"])

    return redirect("/new_graph/")


@csrf_exempt
def upload_gantt(request):
    """
    Загрузка графа в виде файла в исторический граф
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")

    if request.method == "POST":

        files = request.FILES.getlist("file_field")

        global graph_data
        graph_data = []
        graph_data.extend(net_hierarhy.main([f.temporary_file_path() for f in files]))
        user_graph = neo4jexplorer.Neo4jExplorer(uri=URL)
        try:
            user_graph.restore_graph()
        except Exception as e:
            print("views.py 352", e.args)
        dins = {r["wbs3_id"] for r in graph_data if r["wbs3_id"]}
        user_graph.create_new_graph_algo(dins)
        graph_data.sort(
            key=lambda x: (
                x.get("wbs1", "") or "",
                x.get("wbs2", "") or "",
                x.get("wbs3_id", "") or "",
                x.get("wbs3", "") or "",
            )
        )
        return render(
            request,
            "myapp/volumes.html",
            {
                "myJson": graph_data,
            },
        )

    return redirect("/schedule/")


class FileFieldFormView(FormView):
    form_class = FileFieldForm
    template_name = "myapp/new_gantt.html"  # Replace with your template.
    success_url = "/schedule/"  # Replace with your URL or reverse(). "upload_gantt"

    def post(self, request, *args, **kwargs):
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        files = request.FILES.getlist("file_field")
        if form.is_valid():
            for f in files:
                print(f)
            return self.form_valid(form)
        else:
            return self.form_invalid(form)


def excel_upload(request):
    if request.method == "POST":
        path = request.FILES['excel_file']
        d_js = pd.read_excel(
            path,
            dtype=str,
        )
        request.session["gantt"] = 'excel'
        user_graph = neo4jexplorer.Neo4jExplorer(uri=URL)
        try:
            user_graph.single_graph_copy()
        except Exception as e:
            print("views.py 402 Cannot copy historical graph", e.args)

        user_graph.create_new_graph_algo(set(d_js['Шифр'].unique()))

        global graph_data
        graph_data = user_graph.get_nodes(d_js)

        d_js['wbs'] = d_js[['Наименование локальной сметы', '№ п/п']].apply(
            lambda x: ''.join((re.search(r'№\S*', x[0]).group(0)[1:], '.', str(x[1]))), axis=1
        )
        d_js['number'] = d_js['Наименование локальной сметы'].apply(
            lambda x: int(re.search(r'№\S*', x).group(0)[1:].split('-')[0])
        )
        d_js.rename(
            columns={
                'Проект': 'wbs1',
                'Наименование локальной сметы': 'wbs2',
                'Шифр': 'wbs3',
                'Строка сметы': 'name',
                'Объем': 'value',
                '№ п/п': 'Пункт',
            },
            inplace=True
        )
        d_js['wbs3_id'] = d_js['wbs3']
        d_js['Предшественник'] = None

        myJson = d_js.to_dict('records')
        myJson.sort(
            key=lambda x: (
                x.get("number", "") or "",
                x.get("wbs", "") or ""
            )
        )

        global df
        df = d_js
        # df.to_excel('out.xlsx', index=False)
        # print(myJson)
        # переделать template под pandas
        # вставлять готовый текст
        return render(
            request,
            "myapp/excel_table.html",
            {
                "myJson": myJson,
            }
        )

    return render(
        request,
        "myapp/excel.html",
        {
            "uploading": 'excel',
        }
    )


def volumes(request, project_id):
    """
    Ведомость объемов
    :param request:
    :return:vol
    """
    request.session["gantt"] = 'excel'
    project = ActiveLink.objects.filter(userId=request.user.id).last()
    if not project:
        project = ActiveLink()
        project.projectId = None
        project.modelId = None
    request.session["project_id"] = project_id
    project = Project.objects.get(id=project_id)
    response = requests.get(f'http://viewer:8070/load/{project.name}/')
    data = json.loads(response.json())
    for i in range(len(data)):
        data[i]['wbs'] = f"{data[i]['wbs1']}{data[i]['wbs4_id']}"
    for i in range(len(data)):
        if data[i]['distance'] is None:
            data[i]['distance'] = 0
    for i in range(len(data)):
        data[i] = {k: (str(0) if v is None else v) for k, v in data[i].items()}
    global graph_data
    graph_data = data.copy()
    data = [{k: v for k, v in d.items() if k != 'distance'} for d in data]
    wbs = {}
    for node in graph_data:
        if node['wbs1'] not in wbs.keys():
            wbs[node['wbs1']] = {}

        if node['wbs2'] not in wbs[node['wbs1']].keys():
            wbs[node['wbs1']][node['wbs2']] = {}

        if node['wbs3'] not in wbs[node['wbs1']][node['wbs2']]:
            wbs[node['wbs1']][node['wbs2']][node['wbs3']] = {}

        if node['wbs4'] not in wbs[node['wbs1']][node['wbs2']][node['wbs3']]:
            wbs[node['wbs1']][node['wbs2']][node['wbs3']][node['wbs4']] = []

        wbs[node['wbs1']][node['wbs2']][node['wbs3']][node['wbs4']].append(node)

    final = []
    for el in sorted(wbs):
        final.append(
            {'id': '', 'wbs1': el, 'wbs2': '', 'wbs3': '', 'wbs4_id': '', 'wbs4': '', 'name': '', 'distance': ''})
        for subel in sorted(wbs[el]):
            final.append({'id': '', 'wbs1': el, 'wbs2': subel, 'wbs3': '', 'wbs4_id': '', 'wbs4': '', 'name': '',
                          'distance': ''})
            for miniel in sorted(wbs[el][subel]):
                final.append(
                    {'id': '', 'wbs1': el, 'wbs2': subel, 'wbs3': miniel, 'wbs4_id': '', 'wbs4': '', 'name': '',
                     'distance': ''})
                for picoel in sorted(wbs[el][subel][miniel]):
                    final.append(
                        {'id': '', 'wbs1': el, 'wbs2': subel, 'wbs3': miniel, 'wbs4_id': '', 'wbs4': picoel, 'name': '',
                         'distance': ''})
                    for nanoel in wbs[el][subel][miniel][picoel]:
                        final.append(nanoel)

    last_lvl = [0, 0, 0, 0, 0]
    for i, el in enumerate(final):
        if not el['wbs2']:
            last_lvl[0] += 1
            last_lvl[1] = 0
            last_lvl[2] = 0
            last_lvl[3] = 0
            last_lvl[4] = 0
            print(f'lvl1 {last_lvl[0]}')
            final[i].update({'lvl1': last_lvl[0], 'lvl2': '', 'lvl3': '', 'lvl4': '', 'lvl5': '',
                             'p_lvl1': '', 'p_lvl2': '', 'p_lvl3': '', 'p_lvl4': '', 'p_lvl5': ''})
            continue
        elif not el['wbs3']:
            last_lvl[1] += 1
            last_lvl[2] = 0
            last_lvl[3] = 0
            last_lvl[4] = 0
            print(f'lvl2 {last_lvl[0]} {last_lvl[1]}')
            final[i].update({'lvl1': last_lvl[0], 'lvl2': last_lvl[1], 'lvl3': '', 'lvl4': '', 'lvl5': '',
                             'p_lvl1': last_lvl[0], 'p_lvl2': '', 'p_lvl3': '', 'p_lvl4': '', 'p_lvl5': ''})
            continue
        elif not el['wbs4_id']:
            last_lvl[2] += 1
            last_lvl[3] = 0
            last_lvl[4] = 0
            print(f'lvl3 {last_lvl[0]} {last_lvl[1]} {last_lvl[2]}')
            final[i].update({'lvl1': last_lvl[0], 'lvl2': last_lvl[1], 'lvl3': last_lvl[2], 'lvl4': '', 'lvl5': '',
                             'p_lvl1': last_lvl[0], 'p_lvl2': last_lvl[1], 'p_lvl3': '', 'p_lvl4': '', 'p_lvl5': ''})
            continue
        elif not el['id']:
            last_lvl[3] += 1
            last_lvl[4] = 0
            print(f'lvl4 {last_lvl[0]} {last_lvl[1]} {last_lvl[2]} {last_lvl[3]}')
            final[i].update(
                {'lvl1': last_lvl[0], 'lvl2': last_lvl[1], 'lvl3': last_lvl[2], 'lvl4': last_lvl[3], 'lvl5': '',
                 'p_lvl1': last_lvl[0], 'p_lvl2': last_lvl[1], 'p_lvl3': last_lvl[2], 'p_lvl4': '', 'p_lvl5': ''})
            continue
        else:
            last_lvl[4] += 1
            print(f'lvl4 {last_lvl[0]} {last_lvl[1]} {last_lvl[2]} {last_lvl[3]} {last_lvl[4]}')
            final[i].update({'lvl1': last_lvl[0], 'lvl2': last_lvl[1], 'lvl3': last_lvl[2], 'lvl4': last_lvl[3],
                             'lvl5': last_lvl[4],
                             'p_lvl1': last_lvl[0], 'p_lvl2': last_lvl[1], 'p_lvl3': last_lvl[2], 'p_lvl4': last_lvl[3],
                             'p_lvl5': ''})

    text = ''
    for el in final:
        if el['lvl2'] == '':
            text += f'''
                <tr data-node="treetable-{el['lvl1']}" data-pnode="">
                    <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
                </tr>
                '''
            continue
        if el['lvl3'] == '':
            text += f'''
                <tr data-node="treetable-{el['lvl1']}.{el['lvl2']}" data-pnode="treetable-parent-{el['p_lvl1']}">
                    <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
                </tr>
                '''
            continue
        if el['lvl4'] == '':
            text += f'''
                <tr data-node="treetable-{el['lvl1']}.{el['lvl2']}.{el['lvl3']}" data-pnode="treetable-parent-{el['p_lvl1']}.{el['p_lvl2']}">
                    <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
                </tr>
                '''
            continue
        if el['lvl5'] == '':
            text += f'''
                <tr data-node="treetable-{el['lvl1']}.{el['lvl2']}.{el['lvl3']}.{el['lvl4']}" data-pnode="treetable-parent-{el['p_lvl1']}.{el['p_lvl2']}.{el['p_lvl3']}">
                    <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
                </tr>
                '''
            continue

        text += f'''
            <tr data-node="treetable-{el['lvl1']}.{el['lvl2']}.{el['lvl3']}.{el['lvl4']}.{el['lvl5']}" data-pnode="treetable-parent-{el['p_lvl1']}.{el['p_lvl2']}.{el['p_lvl3']}.{el['p_lvl4']}">
                <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
            </tr>
            '''
    return render(
        request,
        "myapp/volumes.html",
        {
            "text": text
        },
    )


def adcm_volumes(request, project_id):
    """
    Ведомость объемов
    :param request:
    :return:vol
    """
    request.session["gantt"] = 'adcm'
    project = ActiveLink.objects.filter(userId=request.user.id).last()
    if not project:
        project = ActiveLink()
        project.projectId = None
        project.modelId = None
    request.session["project_id"] = project_id
    # project = Project.objects.get(id=project_id)
    jwt_request = requests.post(''.join([API_ADDRESS, '/api/fetch/connect']), 
                             json={
                                 "url": API_DB_URL,
                                 "db": API_DB,
                                 "login": API_LOGIN,
                                 "password": API_PASSWORD
                                 })
# print(jwt_request.status_code)                                 
    jwt = jwt_request.text
    response = requests.get(f'http://viewer:8070/copy/{project_id}/', headers={"Authorization": f"Bearer {jwt}"}, params={'jwt': jwt})
    if response.status_code == 404:
        return render(
            request,
            "myapp/error.html",
            {
                "error": ' '.join(('Ошибка:', response.json().get("message")))
            },
        )

    response = requests.get(f'http://viewer:8070/load/{project_id}/')
    # logger.error(response.status_code)
    if response.status_code == 404:
        return render(
            request,
            "myapp/error.html",
            {
                "error": ' '.join(('Ошибка:', response.json().get("message")))
            },
        )
    
    data = json.loads(response.json())
    # try:    
    #     data = json.loads(response.json())

    # except:
    #     # return JsonResponse({'Ошибка':'Отсутсвует ADCM в модели'})
    #     return render(
    #         request,
    #         "myapp/error.html",
    #         {
    #             "error": 'Ошибка: Отсутсвует ADCM в модели'
    #         },
    #     )
    for i in range(len(data)):
        data[i]['wbs'] = f"{data[i]['wbs1']}{data[i]['wbs4_id']}"
    for i in range(len(data)):
        if data[i]['distance'] is None:
            data[i]['distance'] = 0
    for i in range(len(data)):
        data[i] = {k: (str(0) if v is None else v) for k, v in data[i].items()}
    global graph_data
    graph_data = data.copy()
    data = [{k: v for k, v in d.items() if k != 'distance'} for d in data]
    wbs = {}

    for i in range(len(graph_data)):
        messages = [
        {
            "role": "system",
            "text": f"Придумай одно короткое название для действия-работы при строительстве. Сохраняй уникальный цифровой идентификатор",
        },
        {
            "role": "user",
            "text": graph_data[i]['name'],
        },
        ]

        result = model.run(messages)
        graph_data[i]['name'] = ' Оригинал: '.join((result.alternatives[0].text.replace('.',''), graph_data[i]['name']))
    
    for node in graph_data:
        if node['wbs1'] not in wbs.keys():
            wbs[node['wbs1']] = {}

        if node['wbs2'] not in wbs[node['wbs1']].keys():
            wbs[node['wbs1']][node['wbs2']] = {}

        if node['wbs3'] not in wbs[node['wbs1']][node['wbs2']]:
            wbs[node['wbs1']][node['wbs2']][node['wbs3']] = {}

        if node['wbs4'] not in wbs[node['wbs1']][node['wbs2']][node['wbs3']]:
            wbs[node['wbs1']][node['wbs2']][node['wbs3']][node['wbs4']] = []

        
        # print(f"{result.alternatives[0].text.replace('.','')}", end = '')

        # wbs[node['wbs1']][node['wbs2']][node['wbs3']][node['wbs4']]['name'] = result.alternatives[0].text.replace('.','')

        wbs[node['wbs1']][node['wbs2']][node['wbs3']][node['wbs4']].append(node)

    final = []
    for el in sorted(wbs):
        final.append(
            {'id': '', 'wbs1': el, 'wbs2': '', 'wbs3': '', 'wbs4_id': '', 'wbs4': '', 'name': '', 'distance': ''})
        for subel in sorted(wbs[el]):
            final.append({'id': '', 'wbs1': el, 'wbs2': subel, 'wbs3': '', 'wbs4_id': '', 'wbs4': '', 'name': '',
                          'distance': ''})
            for miniel in sorted(wbs[el][subel]):
                final.append(
                    {'id': '', 'wbs1': el, 'wbs2': subel, 'wbs3': miniel, 'wbs4_id': '', 'wbs4': '', 'name': '',
                     'distance': ''})
                for picoel in sorted(wbs[el][subel][miniel]):
                    final.append(
                        {'id': '', 'wbs1': el, 'wbs2': subel, 'wbs3': miniel, 'wbs4_id': '', 'wbs4': picoel, 'name': '',
                         'distance': ''})
                    for nanoel in wbs[el][subel][miniel][picoel]:
                        final.append(nanoel)

    last_lvl = [0, 0, 0, 0, 0]
    for i, el in enumerate(final):
        if not el['wbs2']:
            last_lvl[0] += 1
            last_lvl[1] = 0
            last_lvl[2] = 0
            last_lvl[3] = 0
            last_lvl[4] = 0
            print(f'lvl1 {last_lvl[0]}')
            final[i].update({'lvl1': last_lvl[0], 'lvl2': '', 'lvl3': '', 'lvl4': '', 'lvl5': '',
                             'p_lvl1': '', 'p_lvl2': '', 'p_lvl3': '', 'p_lvl4': '', 'p_lvl5': ''})
            continue
        elif not el['wbs3']:
            last_lvl[1] += 1
            last_lvl[2] = 0
            last_lvl[3] = 0
            last_lvl[4] = 0
            print(f'lvl2 {last_lvl[0]} {last_lvl[1]}')
            final[i].update({'lvl1': last_lvl[0], 'lvl2': last_lvl[1], 'lvl3': '', 'lvl4': '', 'lvl5': '',
                             'p_lvl1': last_lvl[0], 'p_lvl2': '', 'p_lvl3': '', 'p_lvl4': '', 'p_lvl5': ''})
            continue
        elif not el['wbs4_id']:
            last_lvl[2] += 1
            last_lvl[3] = 0
            last_lvl[4] = 0
            print(f'lvl3 {last_lvl[0]} {last_lvl[1]} {last_lvl[2]}')
            final[i].update({'lvl1': last_lvl[0], 'lvl2': last_lvl[1], 'lvl3': last_lvl[2], 'lvl4': '', 'lvl5': '',
                             'p_lvl1': last_lvl[0], 'p_lvl2': last_lvl[1], 'p_lvl3': '', 'p_lvl4': '', 'p_lvl5': ''})
            continue
        elif not el['id']:
            last_lvl[3] += 1
            last_lvl[4] = 0
            print(f'lvl4 {last_lvl[0]} {last_lvl[1]} {last_lvl[2]} {last_lvl[3]}')
            final[i].update(
                {'lvl1': last_lvl[0], 'lvl2': last_lvl[1], 'lvl3': last_lvl[2], 'lvl4': last_lvl[3], 'lvl5': '',
                 'p_lvl1': last_lvl[0], 'p_lvl2': last_lvl[1], 'p_lvl3': last_lvl[2], 'p_lvl4': '', 'p_lvl5': ''})
            continue
        else:
            last_lvl[4] += 1
            print(f'lvl4 {last_lvl[0]} {last_lvl[1]} {last_lvl[2]} {last_lvl[3]} {last_lvl[4]}')
            final[i].update({'lvl1': last_lvl[0], 'lvl2': last_lvl[1], 'lvl3': last_lvl[2], 'lvl4': last_lvl[3],
                             'lvl5': last_lvl[4],
                             'p_lvl1': last_lvl[0], 'p_lvl2': last_lvl[1], 'p_lvl3': last_lvl[2], 'p_lvl4': last_lvl[3],
                             'p_lvl5': ''})

    text = ''
    for el in final:
        if el['lvl2'] == '':
            text += f'''
                <tr data-node="treetable-{el['lvl1']}" data-pnode="">
                    <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
                </tr>
                '''
            continue
        if el['lvl3'] == '':
            text += f'''
                <tr data-node="treetable-{el['lvl1']}.{el['lvl2']}" data-pnode="treetable-parent-{el['p_lvl1']}">
                    <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
                </tr>
                '''
            continue
        if el['lvl4'] == '':
            text += f'''
                <tr data-node="treetable-{el['lvl1']}.{el['lvl2']}.{el['lvl3']}" data-pnode="treetable-parent-{el['p_lvl1']}.{el['p_lvl2']}">
                    <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
                </tr>
                '''
            continue
        if el['lvl5'] == '':
            text += f'''
                <tr data-node="treetable-{el['lvl1']}.{el['lvl2']}.{el['lvl3']}.{el['lvl4']}" data-pnode="treetable-parent-{el['p_lvl1']}.{el['p_lvl2']}.{el['p_lvl3']}">
                    <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
                </tr>
                '''
            continue
        
        text += f'''
            <tr data-node="treetable-{el['lvl1']}.{el['lvl2']}.{el['lvl3']}.{el['lvl4']}.{el['lvl5']}" data-pnode="treetable-parent-{el['p_lvl1']}.{el['p_lvl2']}.{el['p_lvl3']}">
                <td>{el['wbs1']}</td><td>{el['wbs2']}</td><td>{el['wbs3']}</td><td>{el['wbs4_id']}</td><td>{el['wbs4']}</td><td>{el['id']}</td><td>{el['name']}</td>
            </tr>
            '''
    return render(
        request,
        "myapp/volumes.html",
        {
            "text": text
        },
    )


def hist_gantt(request):
    """
    Диаграмма Ганта для исторического графа
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    hist_graph = neo4jexplorer.Neo4jExplorer(uri=URL)
    hist_graph.single_graph_copy()

    if "hist_restored" not in request.session:
        request.session["hist_restored"] = True
    Task2.objects.all().delete()
    Link.objects.all().delete()

    for edge in hist_graph.get_edges():
        Link(
            source=edge["source"],
            target=edge["target"],
            type=edge["type"],
            lag=edge["lag"]
        ).save()

    duration = 1
    for node in hist_graph.get_nodes():
        Task2(
            id=node.get("id"),
            text=node.get("name") + " GESN-" + node.get("id"),
            start_date=datetime.today() + timedelta(days=node.get("distance") or 0),
            duration=duration,
        ).save()

    return render(request, "myapp/new_gantt.html")


def schedule(request):
    """
    Диаграмма Ганта
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    wbs = {}
    Task2.objects.all().delete()
    Link.objects.all().delete()
    for node in graph_data:
        if node['wbs1'] not in wbs.keys():
            wbs[node['wbs1']] = {}
            Task2(
                id=node['wbs1'],
                text=node['wbs1'],
                # min(start_date of levels)
                start_date=datetime.today() + timedelta(
                    days=min([el['distance'] for el in graph_data if el['wbs1'] == node['wbs1']])),
                end_date=datetime.today() + timedelta(
                    days=max([el['distance'] for el in graph_data if el['wbs1'] == node['wbs1']]) + 1)
                # duration = max([distances[din] for din in result[wbs1]])
                # duration=1

            ).save()
        if node['wbs2'] not in wbs[node['wbs1']].keys():
            wbs[node['wbs1']][node['wbs2']] = {}
            Task2(
                id=f"{node['wbs1']}{node['wbs2']}",
                text=node['wbs2'],
                # min(start_date of levels)
                start_date=datetime.today() + timedelta(days=min([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'])])),
                end_date=datetime.today() + timedelta(days=max([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'])]) + 1),
                # duration = max([distances[din] for din in result[wbs1]])
                # duration=1,
                parent=node['wbs1']
            ).save()
        if node['wbs3'] not in wbs[node['wbs1']][node['wbs2']]:
            wbs[node['wbs1']][node['wbs2']][node['wbs3']] = []
            Task2(
                id=f"{node['wbs1']}{node['wbs2']}{node['wbs3']}",
                text=f"{node['wbs3']}",
                # min(start_date of levels)
                start_date=datetime.today() + timedelta(days=min([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'] and el['wbs3'] == node[
                    'wbs3'])])),
                end_date=datetime.today() + timedelta(days=max([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'] and el['wbs3'] == node[
                    'wbs3'])]) + 1),
                # duration = max([distances[din] for din in result[wbs1]])
                # duration=1,
                parent=f"{node['wbs1']}{node['wbs2']}"
            ).save()

        Task2(
            id=f"{node['id']}",
            text=node['name'],
            # min(start_date of levels)
            start_date=datetime.today() + timedelta(days=node['distance']),
            # duration = max([distances[din] for din in result[wbs1]])
            duration=1,
            parent=f"{node['wbs1']}{node['wbs2']}{node['wbs3']}"
        ).save()
        print(node['distance'])
    # project_id = request.session["project_id"]
    # project = Project.objects.get(id=project_id)
    # response = requests.get(f'http://viewer:8070/links/{project.name}/')
    user_graph = neo4jexplorer.Neo4jExplorer(uri=URL)
    data = user_graph.get_edges()
    # data = json.loads(response.json())
    for el in data:
        Link(
            source=str(el['source']),
            target=str(el['target']),
            type=str(el['type']),
            lag=el['lag'],
        ).save()
    return render(request, "myapp/new_gantt.html")


def adcm_schedule(request):
    """
    Диаграмма Ганта
    :param request:
    :return:
    """
    if not request.user.is_authenticated:
        return redirect("/login/")
    if request.session["gantt"] == 'excel':
        return redirect("/schedule/")
    wbs = {}
    Task2.objects.all().delete()
    Link.objects.all().delete()
    for node in graph_data:
        if node['wbs1'] not in wbs.keys():
            wbs[node['wbs1']] = {}
            Task2(
                id=node['wbs1'],
                text=node['wbs1'],
                # min(start_date of levels)
                start_date=datetime.today() + timedelta(
                    days=min([el['distance'] for el in graph_data if el['wbs1'] == node['wbs1']])),
                end_date=datetime.today() + timedelta(
                    days=max([el['distance'] for el in graph_data if el['wbs1'] == node['wbs1']]) + 1)
                # duration = max([distances[din] for din in result[wbs1]])
                # duration=1

            ).save()
        if node['wbs2'] not in wbs[node['wbs1']].keys():
            wbs[node['wbs1']][node['wbs2']] = {}
            Task2(
                id=f"{node['wbs1']}{node['wbs2']}",
                text=node['wbs2'],
                # min(start_date of levels)
                start_date=datetime.today() + timedelta(days=min([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'])])),
                end_date=datetime.today() + timedelta(days=max([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'])]) + 1),
                # duration = max([distances[din] for din in result[wbs1]])
                # duration=1,
                parent=node['wbs1']
            ).save()
        if node['wbs3'] not in wbs[node['wbs1']][node['wbs2']]:
            wbs[node['wbs1']][node['wbs2']][node['wbs3']] = []
            Task2(
                id=f"{node['wbs1']}{node['wbs2']}{node['wbs3']}",
                text=f"{node['wbs3']}",
                # min(start_date of levels)
                start_date=datetime.today() + timedelta(days=min([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'] and el['wbs3'] == node[
                    'wbs3'])])),
                end_date=datetime.today() + timedelta(days=max([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'] and el['wbs3'] == node[
                    'wbs3'])]) + 1),
                # duration = max([distances[din] for din in result[wbs1]])
                # duration=1,
                parent=f"{node['wbs1']}{node['wbs2']}"
            ).save()
        if node['wbs4'] not in wbs[node['wbs1']][node['wbs2']][node['wbs3']]:
            wbs[node['wbs1']][node['wbs2']][node['wbs3']].append(node['wbs4'])
            Task2(
                id=f"{node['wbs1']}{node['wbs2']}{node['wbs3']}{node['wbs4']}",
                text=f"({node['wbs4_id']}) {node['wbs4']}",
                # min(start_date of levels)
                start_date=datetime.today() + timedelta(days=min([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'] and el['wbs3'] == node['wbs3'] and
                        el['wbs4'] == node['wbs4'])])),
                end_date=datetime.today() + timedelta(days=max([el['distance'] for el in graph_data if (
                        el['wbs1'] == node['wbs1'] and el['wbs2'] == node['wbs2'] and el['wbs3'] == node['wbs3'] and
                        el['wbs4'] == node['wbs4'])]) + 1),
                # duration = max([distances[din] for din in result[wbs1]])
                # duration=1,
                parent=f"{node['wbs1']}{node['wbs2']}{node['wbs3']}"
            ).save()

        Task2(
            id=f"{node['id']}",
            text=node['name'],
            # min(start_date of levels)
            start_date=datetime.today() + timedelta(days=node['distance']),
            # duration = max([distances[din] for din in result[wbs1]])
            duration=1,
            parent=f"{node['wbs1']}{node['wbs2']}{node['wbs3']}{node['wbs4']}"
        ).save()
    project_id = request.session["project_id"]
    # project = Project.objects.get(id=project_id)
    response = requests.get(f'http://viewer:8070/links/{project_id}/')
    data = json.loads(response.json())
    for el in data:
        Link(
            source=str(el['source']),
            target=str(el['target']),
            type=str(el['type']),
            lag=el['lag'],
        ).save()
    return render(request, "myapp/new_gantt.html")


@csrf_exempt
def add_link(request):
    if not request.user.is_authenticated:
        return redirect("/login/")
    session = data_collect.authentication(url=X2_URL, user=USER, password=X2_PASS)
    add.edge(session, request.POST["from_din"], request.POST["to_din"], request.POST["weight"])
    session.close()
    return redirect("/new_graph/")


@csrf_exempt
def add_node(request):
    if not request.user.is_authenticated:
        return redirect("/login/")
    session = data_collect.authentication(url=X2_URL, user=USER, password=X2_PASS)
    add.node(session=session, node_din=request.POST["din"], node_name=request.POST["name"])
    session.close()
    return redirect("/new_graph/")


def new_gantt(request):
    return render(request, "myapp/new_gantt.html")


@api_view(["GET"])
@authentication_classes([BasicAuthentication])
@permission_classes([AllowAny])
def data_list(request, offset):
    if request.method == "GET":
        tasks = Task2.objects.all()
        links = Link.objects.all()
        task_data = TaskSerializer(tasks, many=True)
        link_data = LinkSerializer(links, many=True)
        return Response({"tasks": task_data.data, "links": link_data.data})
