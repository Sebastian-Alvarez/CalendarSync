import sys
import json
import datetime
import requests
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# -------------------------------------------------- Var. Globales ------------------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]
BASE_DIR = Path(__file__).resolve().parent
saCredentials = BASE_DIR / ".secrets" / "service-account.json"
notionSecret = BASE_DIR / ".secrets" / "notion.txt"
calendarID = "a4e2b55b85135005172885d8ae0d81476c38d582d42efcb4883fbd2d08e8e9da@group.calendar.google.com"
evaluacionesDatabaseID = "c19a268ed8b34fd78ee366b631a0c43d"
notionFechaProp = "Fecha inicio"
notionEntregaProp = "Entrega"
notionRamoRelationProp = "Ramo"
# ------------------------------------------------------ Main -----------------------------------------------------------------------
def main():
    try:
        credentials = getCredential()
        service = connectGCal(credentials)
        calendar = service.calendars().get(calendarId=calendarID).execute()
        testConnection(service, calendar)
        if notionConnection():
            evaluaciones = getEvaluacionesFromNotion()
            print("\nEvaluaciones encontradas:")
            if not evaluaciones:
                print("No se encontraron evaluaciones con fecha.")
            else:
                for item in evaluaciones:
                    ramos = ", ".join(item["ramos"]) if item["ramos"] else "(sin ramo)"
                    print(f"- {item['fecha_inicio']} | {item['evaluacion']} | {ramos}")
    except Exception as e:
        print(f"Error inesperado: {e}")
# ---------------------------------------------- Google Connection ------------------------------------------------------------------
def getCredential():
    try:
        credential = service_account.Credentials.from_service_account_file(
            str(saCredentials),
            scopes=SCOPES,
        )
        return credential
    except ValueError:
        print("Unable to authenticate using service account key.")
        sys.exit()
def connectGCal(credentials):
    try:
        service = build("calendar", "v3", credentials=credentials)
        return service
    except Exception as e:
        print(f"Error al conectar con Google Calendar: {e}")
        sys.exit()
def testConnection(service, calendar):
    try:
        print(f"Calendario: {calendar['summary']}")
        print(f"Zona horaria: {calendar['timeZone']}")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId=calendarID,
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
        print("\nPróximos eventos:")
        if not events:
            print("No hay eventos próximos.")
        else:
            for event in events:
                start = event["start"].get("dateTime", event["start"].get("date"))
                print(f"- {start} | {event.get('summary', '(sin título)')}")
    except HttpError as e:
        print(f"Error HTTP de Google Calendar: {e}")
# ---------------------------------------------------- Notion  ----------------------------------------------------------------------
def notionRequest(method, endpoint, payload=None):
    token = notionSecret.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("El token de Notion está vacío.")
    response = requests.request(
        method,
        f"https://api.notion.com/v1{endpoint}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": "2026-03-11",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
def notionConnection():
    try:
        notionRequest("POST", "/search", {
            "filter": {"value": "page", "property": "object"},
            "page_size": 1,
        })
        print("\nConexión con Notion OK")
        return True
    except RuntimeError as e:
        print(e)
    except requests.exceptions.Timeout:
        print("Timeout al conectar con Notion.")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "desconocido"
        try:
            error_body = e.response.json() if e.response is not None else {}
        except ValueError:
            error_body = e.response.text if e.response is not None else ""
        print(f"Error HTTP al conectar con Notion: {status}")
        print(error_body)
    except requests.exceptions.RequestException as e:
        print(f"Error de red al conectar con Notion: {e}")
    except ValueError:
        print("La respuesta de Notion no vino en formato JSON válido.")

    return False
def getEvaluacionesFromNotion():
    database = notionRequest("GET", f"/databases/{evaluacionesDatabaseID}")
    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise RuntimeError("No se encontraron data sources para la base de Evaluaciones.")
    
    dataSourceID = data_sources[0]["id"]
    pages = []
    start_cursor = None
    ramoCache = {}
    
    while True:
        payload = {
            "page_size": 100,
            "filter": {
                "property": notionFechaProp,
                "date": {
                    "is_not_empty": True
                }
            }
        }
        if start_cursor:
            payload["start_cursor"] = start_cursor
        data = notionRequest("POST", f"/data_sources/{dataSourceID}/query", payload)
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break 
        start_cursor = data.get("next_cursor")
    
    evaluaciones = []
    
    for page in pages:
        properties = page.get("properties", {})
        # ----------- Título ------------
        evaluacionTitulo = ""
        for prop in properties.values():
            if prop.get("type") == "title":
                evaluacionTitulo = getPlainText(prop.get("title", []))
                break
        fecha = properties.get(notionFechaProp, {}).get("date") or {}
        entrega = properties.get(notionEntregaProp, {}).get("date") or {}
        ramoRefs = properties.get(notionRamoRelationProp, {}).get("relation", [])
        fechaEvaluacion = {}
        ramos = []
        # ---- Evaluación de Fechas -----
        if(entrega.get("start") is None):
            fechaEvaluacion = fecha
        else:
            if(datetime.datetime.now().isoformat() > fecha.get("start")):
                fechaEvaluacion = entrega
            else:
                fechaEvaluacion = fecha
        # ------------ Ramos ------------
        for item in ramoRefs:
            ramoID = item["id"]
            if ramoID in ramoCache:
                ramos.append(ramoCache[ramoID])
                continue
            ramoPage = notionRequest("GET", f"/pages/{ramoID}")
            ramoProperties = ramoPage.get("properties", {})
            ramoTitle = ramoID
            for prop in ramoProperties.values():
                if prop.get("type") == "title":
                    ramoTitle = getPlainText(prop.get("title", [])) or ramoID
                    break
            ramoCache[ramoID] = ramoTitle
            ramos.append(ramoTitle)
        evaluaciones.append({
            "notion_page_id": page["id"],
            "evaluacion": evaluacionTitulo,
            "fecha_inicio": fechaEvaluacion.get("start"),
            "fecha_fin": fechaEvaluacion.get("end"),
            "time_zone": fechaEvaluacion.get("time_zone") or fecha.get("time_zone"),
            "ramos": ramos,
        })
    
    return evaluaciones
# -----------------------------------------------------------------------------------------------------------------------------------
def getPlainText(items):
    return "".join(item.get("plain_text", "") for item in items)
# -----------------------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    print("")
    main()