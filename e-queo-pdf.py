import requests
import json
from fake_useragent import UserAgent
from pathvalidate import sanitize_filename
import time
import markdown
from markdown.extensions.toc import TocExtension
import re
import pdfkit
import logging
from pathlib import Path
from configparser import ConfigParser


# logging config
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')


def get_config_data(filename, section, name):
    config = ConfigParser()
    config.read(filename)
    data = ''
    if config.has_section(section):
        data = config[section][name]
    else:
        raise Exception(
            'Section {0} not found in the {1} file'.format(section, filename))

    return data


# token from e-queo.online (from Authorization header)
# lives 3600 s from being refreshed
AUTH_TOKEN = get_config_data('config.ini', 'e-queo', 'auth_token')

# module id from the address bar for your course
MODULE_ID = get_config_data('config.ini', 'e-queo', 'module_id')

# build headers for all the requests
ua = UserAgent()
headers = {'Content-Type': 'application/json;charset=UTF-8',
           'Authorization': f'Bearer {AUTH_TOKEN}', 'User-Agent': ua.random}


def get_learning_programs():
    programs = {}
    page_num = 1
    has_next = True

    def lambda_extract_sections(section):
        def lambda_extract_materials(material):
            return {
                'id': material['id'],
                'name': material['name'],
                'order': material['order']
            }

        return {
            'id': section['id'],
            'name': section['name'],
            'order': section['order'],
            'materials': list(map(lambda_extract_materials, section['materials']))
        }

    while has_next:
        request_url = f'https://api.e-queo.online/v40/learning-programs?page={page_num}&module_id={MODULE_ID}'
        try:
            response = requests.get(request_url, headers=headers)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise SystemExit(f'Error while getting learning programs. {e}')
        response = response.json()
        for program in response['success']['learning_programs']:
            programs[program['id']] = {
                'name': program['name'],
                'sections': list(map(lambda_extract_sections, program['sections'])),
                'order': program['order']
            }
        has_next = page_num < response['success']['meta']['pagination']['pages_count']
        page_num += 1
    return programs


def get_longread_ids(program):
    materials = []
    longreads_ids = []
    page_num = 1
    has_next = True

    for section in program['sections']:
        for material in section['materials']:
            materials.append(material['id'])
    request_body = {
        'materials': materials
    }
    request_body = json.dumps(request_body, ensure_ascii=False)
    while has_next:
        request_url = f'https://api.e-queo.online/v40/materials-cr?page={page_num}'
        try:
            response = requests.post(request_url,
                                     data=request_body.encode("utf-8"),
                                     headers=headers, verify=True)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise SystemExit(f'Error while getting longread ids. {e}')
        response = response.json()
        longreads_ids += list(map(lambda y: y['id'],
                                  filter(
            lambda x: x['type'] == 'longread', response['success']['materials'])
        ))
        has_next = page_num < response['success']['meta']['pagination']['pages_count']
        page_num += 1
    return longreads_ids


def get_longreads_uuids(longreads_ids):
    longreads = []
    page_num = 1
    has_next = True
    request_body = {
        'longreads': longreads_ids
    }
    request_body = json.dumps(request_body, ensure_ascii=False)
    while has_next:
        request_url = f'https://api.e-queo.online/v40/materials/longreads/pages/titles?page={page_num}'
        try:
            response = requests.post(request_url,
                                     data=request_body.encode("utf-8"),
                                     headers=headers, verify=True)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise SystemExit(f'Error while getting longread uuids. {e}')
        response = response.json()
        longreads += list(map(lambda x: {
            'id': x['longread_id'],
            'uuid': x['uuid']
        }, response['success']['page_titles']))
        has_next = page_num < response['success']['meta']['pagination']['pages_count']
        page_num += 1
    return longreads


def get_longread_content(longread):
    request_url = 'https://api.e-queo.online/v40/materials/longreads/page'
    request_body = {
        'longread': longread['id'],
        'page': longread['uuid']
    }
    request_body = json.dumps(request_body, ensure_ascii=False)
    try:
        response = requests.post(request_url,
                                 data=request_body.encode("utf-8"),
                                 headers=headers, verify=True)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise SystemExit(f'Error while getting longread content. {e}')
    response = response.json()
    return response['success']['page']['body']


def filter_longreads(program, longreads_ids):
    for section in program['sections']:
        section['materials'] = list(
            filter(lambda x: x['id'] in longreads_ids,
                   section['materials'])
        )
    return program


def create_program_content_md(sections, longreads_content):
    program_content_md = ''
    for section in sections:
        materials = sorted(section['materials'], key=lambda x: x['order'])
        for material in materials:
            text = next(
                (x['content'] for x in longreads_content if x['id'] == material['id']), None)
            text = shift_headings(text, 1)
            heading = material['name']
            program_content_md += f'# {heading}\n\n\n{text}\n'
    return program_content_md


def shift_headings(md, level=1):
    shift = '#'*level
    replaced = re.sub(r'^(#+)', r'\1'+shift, md, flags=re.MULTILINE)
    return replaced


def main():
    start_time = time.perf_counter()

    # get all the learning programs
    programs = get_learning_programs()
    logging.info('Prepared all the learning programs')

    # process each program
    for program_id in programs:
        longreads_content = []
        program_content_md = ''

        # get all longreads for the program
        logging.info(
            f'Processing program \"{programs[program_id]["name"]}\"')
        longreads_ids = get_longread_ids(programs[program_id])
        longreads = get_longreads_uuids(longreads_ids)
        for longread in longreads:
            content = get_longread_content(longread)
            longreads_content.append({
                'id': longread['id'],
                'content': content
            })

        # keep only longreads
        programs[program_id] = filter_longreads(
            programs[program_id], longreads_ids)
        sections = sorted(programs[program_id]
                          ['sections'], key=lambda x: x['order'])

        file_name = sanitize_filename(programs[program_id]["name"])

        # create md
        program_content_md = create_program_content_md(
            sections, longreads_content)

        # add TOC marker
        program_content_md = f'[TOC] \n\n{program_content_md}'
        Path("output/md").mkdir(parents=True, exist_ok=True)
        with open(f'output/md/{file_name}.md', 'w') as f:
            f.write(program_content_md)  # for debug

        # create html
        html = markdown.markdown(program_content_md, extensions=[
            TocExtension(title='Оглавление', toc_depth='1')])
        Path("output/html").mkdir(parents=True, exist_ok=True)
        with open(f'output/html/{file_name}.htm', 'w') as f:
            f.write(html)

        # create pdf
        options = {
            'encoding': 'UTF-8',
            'footer-right': '[page]/[topage]',
            'footer-font-size': '10',
            'footer-center': programs[program_id]["name"],
            'footer-spacing': '5',
            'footer-font-name': 'Roboto',
            'margin-top': '16mm',
            'margin-bottom': '20mm',
            'margin-right': '20mm',
            'margin-left': '20mm',
            'user-style-sheet': 'pdf.css',
            'disable-smart-shrinking': None,  # enabled to manually set constant px/dpi ratio
            'zoom': 0.6112,  # a specific value has to be set to normalize the scale for all files, this one is just figured out for my case
        }
        Path("output/pdf").mkdir(parents=True, exist_ok=True)
        pdfkit.from_file(
            f'output/html/{file_name}.htm', f'output/pdf/{file_name}.pdf', options=options)
        logging.info('Done')
    logging.info("--- %s seconds ---" % (time.perf_counter() - start_time))


if __name__ == "__main__":
    main()
