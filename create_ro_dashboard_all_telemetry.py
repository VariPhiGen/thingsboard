import requests
import json

BASE_URL = 'http://localhost:9091'
SYSADMIN_USER = 'sysadmin@thingsboard.org'
SYSADMIN_PASS = 'sysadmin'

def login(username, password):
    url = f"{BASE_URL}/api/auth/login"
    payload = {"username": username, "password": password}
    response = requests.post(url, json=payload, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()['token']

def create_card_widget(w_id, row, col, size_x, size_y, name, label, title, alias_id, unit=""):
    return {
      "typeFullFqn": "system.cards.value_card",
      "type": "latest",
      "sizeX": size_x,
      "sizeY": size_y,
      "row": row,
      "col": col,
      "id": w_id,
      "config": {
        "title": title,
        "showTitle": False, # Hide widget title to prevent double naming
        "showTitleIcon": False,
        "datasources": [
          {
            "type": "entity",
            "name": "",
            "entityAliasId": alias_id,
            "dataKeys": [
              {
                "name": name,
                "type": "timeseries",
                "label": label,
                "color": "#2196f3",
                "units": unit,
                "decimals": 1,
                "settings": {}
              }
            ]
          }
        ],
        "timewindow": {
          "realtime": {
            "realtimeType": 0,
            "interval": 1000,
            "timewindowMs": 60000
          }
        },
        "settings": {
            "autoScale": False,
            "valueFont": {
                "size": 24,
                "sizeUnit": "px",
                "family": "Roboto",
                "weight": "500",
                "style": "normal"
            }
        }
      }
    }

def create_chart_widget(w_id, row, col, size_x, size_y, name, label, title, alias_id, unit=""):
    return {
      "typeFullFqn": "system.charts.basic_timeseries",
      "type": "timeseries",
      "sizeX": size_x,
      "sizeY": size_y,
      "row": row,
      "col": col,
      "id": w_id,
      "config": {
        "title": title,
        "showTitle": True,
        "showTitleIcon": False,
        "datasources": [
          {
            "type": "entity",
            "name": "",
            "entityAliasId": alias_id,
            "dataKeys": [
              {
                "name": name,
                "type": "timeseries",
                "label": label,
                "color": "#4caf50",
                "units": unit,
                "decimals": 1,
                "settings": {}
              }
            ]
          }
        ],
        "timewindow": {
          "realtime": {
            "realtimeType": 0,
            "interval": 1000,
            "timewindowMs": 60000
          }
        },
        "settings": {
            "xaxis": {
                "showLabels": True,
                "color": "#545454"
            },
            "yaxis": {
                "showLabels": True,
                "color": "#545454"
            },
            "grid": {
                "color": "#545454",
                "verticalLines": True,
                "horizontalLines": True,
                "outlineWidth": 1
            }
        }
      }
    }

def main():
    sys_token = login(SYSADMIN_USER, SYSADMIN_PASS)
    sys_headers = {"X-Authorization": f"Bearer {sys_token}", "Content-Type": "application/json"}

    tenant_id = requests.get(f"{BASE_URL}/api/tenants?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    admin_user_id = requests.get(f"{BASE_URL}/api/tenant/{tenant_id}/users?pageSize=10&page=0", headers=sys_headers).json()['data'][0]['id']['id']
    tenant_token = requests.get(f"{BASE_URL}/api/user/{admin_user_id}/token", headers=sys_headers).json()['token']
    tenant_headers = {"X-Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"}

    res_ro = requests.get(f"{BASE_URL}/api/tenant/devices?deviceName=RO Plant System", headers=tenant_headers)
    ro_device_id = res_ro.json()['id']['id']

    alias_id = "ro-plant-alias"
    entity_aliases = {
        alias_id: {
            "id": alias_id,
            "alias": "RO Plant System",
            "filter": {
                "type": "singleEntity",
                "resolveMultiple": False,
                "singleEntity": {
                    "entityType": "DEVICE",
                    "id": ro_device_id
                }
            }
        }
    }

    widgets = {}
    main_widgets_layout = {}
    
    numeric_keys = [
        {"key": "pressure", "label": "Pressure", "unit": "psi"},
        {"key": "salinity_ppm", "label": "Salinity", "unit": "ppm"},
        {"key": "tds_ppm", "label": "TDS", "unit": "ppm"},
        {"key": "temperature_c", "label": "Temperature", "unit": "°C"},
        {"key": "water_flow", "label": "Water Flow", "unit": "L/min"},
        {"key": "ec_us_cm", "label": "EC", "unit": "uS/cm"},
        {"key": "ph", "label": "pH", "unit": ""}
    ]
    
    text_keys = [
        {"key": "status", "label": "Operating Status", "unit": ""},
        {"key": "ping", "label": "Ping", "unit": ""}
    ]
    
    # 4 cards per row instead of 6 to prevent text overlapping
    col_width = 6
    
    current_row = 0
    current_col = 0
    
    # 1. Create Cards for Text Keys
    for item in text_keys:
        w_id = f"w_card_{item['key']}"
        widgets[w_id] = create_card_widget(w_id, current_row, current_col, col_width, 4, item['key'], item['label'], item['label'], alias_id, item['unit'])
        main_widgets_layout[w_id] = {"sizeX": col_width, "sizeY": 4, "row": current_row, "col": current_col}
        current_col += col_width
        if current_col >= 24:
            current_col = 0
            current_row += 4
            
    # 2. Create Cards for Numeric Keys
    for item in numeric_keys:
        w_id = f"w_card_{item['key']}"
        widgets[w_id] = create_card_widget(w_id, current_row, current_col, col_width, 4, item['key'], item['label'], item['label'], alias_id, item['unit'])
        main_widgets_layout[w_id] = {"sizeX": col_width, "sizeY": 4, "row": current_row, "col": current_col}
        current_col += col_width
        if current_col >= 24:
            current_col = 0
            current_row += 4
            
    # 3. Create Charts for Numeric Keys
    if current_col > 0:
        current_row += 4 # Ensure charts start on a new row block
    current_col = 0
    chart_width = 12 # 2 charts per row (wider)
    chart_height = 8 # Taller
    for item in numeric_keys:
        w_id = f"w_chart_{item['key']}"
        widgets[w_id] = create_chart_widget(w_id, current_row, current_col, chart_width, chart_height, item['key'], item['label'], f"{item['label']} History", alias_id, item['unit'])
        main_widgets_layout[w_id] = {"sizeX": chart_width, "sizeY": chart_height, "row": current_row, "col": current_col}
        current_col += chart_width
        if current_col >= 24:
            current_col = 0
            current_row += chart_height
            
    dashboard_config = {
        "description": "Comprehensive RO Plant Dashboard",
        "widgets": widgets,
        "states": {
            "default": {
                "name": "RO Plant Realtime Overview",
                "root": True,
                "layouts": {
                    "main": {
                        "widgets": main_widgets_layout,
                        "gridSettings": {
                            "backgroundColor": "#eeeeee",
                            "columns": 24,
                            "margin": 10,
                            "backgroundSizeMode": "100%"
                        }
                    }
                }
            }
        },
        "entityAliases": entity_aliases,
        "filters": {},
        "timewindow": {
            "displayValue": "",
            "selectedTab": 0,
            "realtime": {
                "realtimeType": 0,
                "interval": 1000,
                "timewindowMs": 60000,
                "quickInterval": "CURRENT_DAY"
            }
        },
        "settings": {
            "stateControllerId": "entity",
            "showTitle": True,
            "showDashboardsSelect": True,
            "showEntitiesSelect": True,
            "showDashboardTimewindow": True,
            "showDashboardExport": True,
            "toolbarAlwaysOpen": True
        }
    }

    dashboards = requests.get(f"{BASE_URL}/api/tenant/dashboards?pageSize=100&page=0", headers=tenant_headers).json()['data']
    target_dashboard = next((d for d in dashboards if 'RO Plant Dashboard' in d['title']), None)

    dashboard_payload = {
        "title": "RO Plant Dashboard",
        "configuration": dashboard_config
    }

    if target_dashboard:
        dashboard_payload["id"] = target_dashboard["id"]
        dashboard_payload["tenantId"] = target_dashboard["tenantId"]

    res = requests.post(f"{BASE_URL}/api/dashboard", json=dashboard_payload, headers=tenant_headers)
    if res.ok:
        print("RO Plant Dashboard successfully updated with ALL telemetry (cards & charts)!")
    else:
        print(f"Failed to update dashboard: {res.text}")

if __name__ == "__main__":
    main()
