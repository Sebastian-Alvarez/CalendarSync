import os
import sys
import json
import datetime
import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# -------------------------------------------------- Var. Globales ------------------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]
LISTA_RAMOS = "ramosIDs.json"
CALENDAR_ID = "a4e2b55b85135005172885d8ae0d81476c38d582d42efcb4883fbd2d08e8e9da@group.calendar.google.com"
NOTION_DATABASE_ID = "c19a268ed8b34fd78ee366b631a0c43d"
NOTION_DATASOURCE_ID = "42740aed-26d6-4d8e-89c5-5baec53d318a"
# ------------------------------------------------------ Main -----------------------------------------------------------------------
def main():
    try:
        load_dotenv()
        credentials = getCredential()
        service = connectGCal(credentials)
        calendar = service.calendars().get(calendarId=CALENDAR_ID).execute()
        testGCConnection(service, calendar)
        testNotionConnection()
        eventosNotion = getEvaluacionesFromNotion()
        filteredNotionEvnets = filterNoSyncEvents(eventosNotion)
        for event in filteredNotionEvnets:
            uploadNew2GCal(service, event)
    except Exception as e:
        print(f"Error inesperado: {e}")
# ------------------------------------------------ Google Connection ----------------------------------------------------------------
def getCredential():
    try:
        service_account = os.getenv("GOOGLE_SERVICE_ACCOUNT")
        if not service_account:
            raise RuntimeError("Credenciales de Google no encontradas.")
        service_account_info = json.loads(service_account)

        credential = service_account.Credentials.from_service_account_info(
            service_account_info,
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
def testGCConnection(service, calendar):
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
        print(f"Conexión con Google Calendar OK\nCalendario: {calendar.get('summary')}")
        if not events:
            print("No hay eventos próximos.")
    except HttpError as e:
        print(f"Error HTTP de Google Calendar: {e}")
def printEventoGcal(event):
    fecha = (
        event.get("start", {}).get("dateTime")
        or event.get("start", {}).get("date")
        or "(sin fecha)"
    )
    titulo = event.get("summary") or "(sin título)"
    print(f"{fecha} | {titulo}")
# ------------------------- CRUD ---------------------------
def createGoogleEvent(service, event):
    try:
        created_event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()
        print("Evento creado en Google Calendar:\t")
        printEventoGcal(created_event)
        return created_event
    except HttpError as e:
        print(f"Error al crear evento en Google Calendar: {e}")
        return None
def updateGoogleEvent(service, eventId, event):
    try:
        updated_event = service.events().update(
            calendarId=CALENDAR_ID, 
            eventId=eventId, 
            body=event
        ).execute()
        print("Evento actualizado en Google Calendar: \t")
        printEventoGcal(updated_event)
    except HttpError as e:
        print(f"Error al actualizar evento en Google Calendar: {e}")
def deleteGoogleEvent(service, id):
    try:
        service.events().delete(
            calendarId=CALENDAR_ID, 
            eventId=id
        ).execute()
        print(f"Evento eliminado en Google Calendar: {id}")
    except HttpError as e:
        print(f"Error al eliminar evento en Google Calendar: {e}")
def getGoogleEvents(service, id):
    try:
        event = service.events().get(
            calendarId=CALENDAR_ID, 
            eventId=id
        ).execute()
        print(f"Evento obtenido de Google Calendar: {event.get('htmlLink')}")
        return event
    except HttpError as e:
        print(f"Error al obtener evento de Google Calendar: {e}")
        return None
# ----------------------------------------------------- Notion  ---------------------------------------------------------------------
def notionRequest(method, endpoint, payload=None):
    token = os.getenv("NOTION_TOKEN")
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
def testNotionConnection():
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
    database = notionRequest("GET", f"/databases/{NOTION_DATABASE_ID}")
    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise RuntimeError("No se encontraron data sources para la base de Evaluaciones.")
    
    _, ramos_por_id = loadRamosMaps()
    dataSourceID = data_sources[0]["id"]
    pages = []
    start_cursor = None
    ramoCache = {}
    while True:
        payload = {
            "page_size": 100,
            "filter": {
                "property": "Fecha inicio",
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
    # ---------------- Propiedades ----------------
    for page in pages:
        properties = page.get("properties", {})
        # ----------- Título ------------
        evaluacionTitulo = ""
        for prop in properties.values():
            if prop.get("type") == "title":
                evaluacionTitulo = getPlainText(prop.get("title", []))
                break
        # ---- Evaluación de Fechas -----
        fechaEvaluacion = {}
        fecha = properties.get("Fecha inicio", {}).get("date") or {}
        entrega = properties.get("Entrega", {}).get("date") or {}
        if(entrega.get("start") is None):
            fechaEvaluacion = fecha
        else:
            if(datetime.datetime.now().isoformat() > fecha.get("start")):
                fechaEvaluacion = entrega
            else:
                fechaEvaluacion = fecha
        # ------------ Ramos ------------
        ramos = []
        ramoRefs = properties.get("Ramo", {}).get("relation", [])
        for item in ramoRefs:
            ramo_id = item.get("id")
            if not ramo_id:
                continue

            ramos.append({
                "nombre": ramos_por_id.get(normalizeNotionId(ramo_id), "RAMO_NO_MAPEADO"),
                "id": ramo_id,
            })

        # ------------ GoogleCal ------------
        gcalID = getPlainText(properties.get("google_id", {}).get("rich_text", []))
        # -----------------------------------
        evaluaciones.append({
            "notion_page_id": page["id"],
            "title": evaluacionTitulo,
            "fecha_inicio": fechaEvaluacion.get("start"),
            "fecha_fin": fechaEvaluacion.get("end"),
            "time_zone": fechaEvaluacion.get("time_zone") or fecha.get("time_zone"),
            "ramos": ramos,
            "gcal_event_id": gcalID,
        })
    print("Eventos de Notion encontradas:",len(pages))
    if not evaluaciones:
        print("No se encontraron evaluaciones.")
    
    return evaluaciones
def printEventoNotion(evento):
    ramos = ", ".join(
        f"{ramo['nombre']} ({ramo['id']})" for ramo in evento["ramos"]
    ) if evento["ramos"] else "(sin ramo)"
    print(f"- {evento['fecha_inicio']} | {evento['title']} | {ramos} | {evento['gcal_event_id']}")
def filterNoSyncEvents(eventos):
    noSync = []
    for item in eventos:
        if not item["gcal_event_id"]:
            noSync.append(item)
    print("Eventos de Notion sin sincronizar:",len(noSync),"\n")
    return noSync
def addGoogleIDtoEvent(gcalEventId):
    return {
        "google_id": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": str(gcalEventId)}
                }
            ]
        }
    }
def normalizeNotionId(value):
    if not value:
        return ""
    return str(value).replace("-", "").lower()
# ------------------------- CRUD ---------------------------
def createNotionEvent(eventInfo):
    try:
        newEvent = notionRequest(
            "POST",
            "/pages",
            {
                "parent": {
                    "type": "data_source_id",
                    "data_source_id": NOTION_DATASOURCE_ID,
                },
                "properties": eventInfo,
            }
        )
        print(f"Evento creado en Notion: {newEvent.get('url')}")
        return newEvent
    except Exception as e:
        print(f"Error al crear evento en Notion: {e}")
        return None   
def updateNotionEvent(eventId, eventInfo):
    try:
        updatedPage = notionRequest(
            "PATCH",
            f"/pages/{eventId}",
            {"properties": eventInfo}
        )
        print(f"Evento actualizado en Notion: {updatedPage.get('url')}")
        return updatedPage
    except Exception as e:
        print(f"Error al actualizar evento en Notion: {e}")
        return None
def deleteNotionEvent(id):
    try:
        deletedPage = notionRequest(
            "PATCH",
            f"/pages/{id}",
            {
                "in_trash": True
            }
        )
        print(f"Evento enviado a la papelera de Notion: {deletedPage.get('url')}")
        return deletedPage
    except Exception as e:
        print(f"Error al eliminar evento en Notion: {e}")
        return None
def getNotionEvent(id):
    try:
        event = notionRequest(
            "GET",
            f"/pages/{id}"
        )
        print(f"Evento obtenido de Notion: {event.get('url')}")
        return event
    except Exception as e:
        print(f"Error al obtener evento de Notion: {e}")
        return None
# -----------------------------------------------------------------------------------------------------------------------------------
def getPlainText(items):
    return "".join(item.get("plain_text", "") for item in items)
def formatNotion2GCal(notionEvent):
    inicio = notionEvent.get("fecha_inicio")
    fin = notionEvent.get("fecha_fin")
    tz = notionEvent.get("time_zone", "America/Santiago")
    nombres_ramos = getRamoNames(notionEvent.get("ramos", []))
    ramo = ", ".join(nombres_ramos)

    if not inicio:
        raise ValueError("El evento no tiene fecha_inicio")

    if "T" not in inicio:
        return {
            "summary": f"{notionEvent['title']} | {ramo}",
            "description": "",
            "start": {"date": inicio},
            "end": {"date": fin or inicio},
            "extendedProperties": {
                "private": {
                    "notion_event_ID": notionEvent["notion_page_id"],
                }
            }
        }

    return {
        "summary": f"{notionEvent['title']} | {ramo}",
        "description": "",
        "start": {
            "dateTime": inicio,
            "timeZone": tz,
        },
        "end": {
            "dateTime": fin or inicio,
            "timeZone": tz,
        },
        "extendedProperties": {
            "private": {
                "notion_event_ID": notionEvent["notion_page_id"],
            }
        }
    }
def loadRamosMaps():
    try:
        path = LISTA_RAMOS
        with path.open("r", encoding="utf-8") as f:
            ramos_por_nombre = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"No se encontró el archivo {LISTA_RAMOS}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{LISTA_RAMOS} no contiene un JSON válido: {e}")

    if not isinstance(ramos_por_nombre, dict):
        raise RuntimeError(f"{LISTA_RAMOS} debe tener formato {{'RAMO': 'id'}}")

    ramos_por_id = {
        normalizeNotionId(ramo_id): nombre
        for nombre, ramo_id in ramos_por_nombre.items()
    }
    return ramos_por_nombre, ramos_por_id
def getRamoNames(ramos):
    nombres = []
    for ramo in ramos:
        if isinstance(ramo, dict):
            nombre = ramo.get("nombre")
            if nombre:
                nombres.append(nombre)
        elif isinstance(ramo, str):
            nombres.append(ramo)
    return nombres
def buildRamoRelation(ramos_input):
    ramos_por_nombre, _ = loadRamosMaps()
    relation = []

    for ramo in ramos_input:
        if isinstance(ramo, dict):
            ramo_id = ramo.get("id") or ramos_por_nombre.get(ramo.get("nombre"))
        else:
            ramo_id = ramos_por_nombre.get(ramo)

        if ramo_id:
            relation.append({"id": ramo_id})
        else:
            print(f"Ramo no encontrado en {LISTA_RAMOS}: {ramo}")

    return {"Ramo": {"relation": relation}}
def uploadNew2GCal(service, notionEvent):
    event = formatNotion2GCal(notionEvent)
    createdEvent = createGoogleEvent(service, event)

    if not createdEvent:
        return None

    gcalEventId = createdEvent.get("id")
    if not gcalEventId:
        print("No se pudo obtener el id del evento creado en Google Calendar.")
        return None

    notionResult = updateNotionEvent(
        notionEvent["notion_page_id"],
        addGoogleIDtoEvent(gcalEventId)
    )

    if not notionResult:
        deleteGoogleEvent(service, gcalEventId)
        return None

    return createdEvent
# -----------------------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    print("")
    main()