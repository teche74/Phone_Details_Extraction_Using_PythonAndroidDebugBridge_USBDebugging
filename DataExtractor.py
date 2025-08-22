from ppadb.client import Client as AdbClient
import subprocess, os,json, re
from datetime import datetime


class PhoneDataCollector:
    def __init__(self, host="127.0.0.1", port=5037):
        self.ensure_adb_server()
        self.client = AdbClient(host, port)
        self.devices = self.client.devices()
        if not self.devices:
            raise RuntimeError("No device connected. Enable USB Debugging and connect a device!")

        print("Devices Available:")
        for index, device in enumerate(self.devices):
            model = device.shell("getprop ro.product.model").strip()
            print(f"{index} : {model} ({device.serial})")
        
        if len(self.devices) == 1:
            index = 0
            print("Only one device found, auto-connecting...")
        else:
            try:
                index = int(input("Enter Device index: "))
                if index < 0 or index >= len(self.devices):
                    raise ValueError("Invalid device index.")
            except ValueError:
                raise ValueError("Please enter a valid number.")

        self.target = self.devices[index]
        model = self.target.shell("getprop ro.product.model").strip()
        print(f"✅ Connected to {model}")

    def ensure_adb_server(self):
        try:
            subprocess.run(["adb", "start-server"], check=True)
        except Exception as e:
            print("⚠️ Failed to start adb server. Make sure adb is installed and in PATH.", e)

    def GetInstalledPackage(self):
        result = self.target.shell("pm list packages")
        return [pkg.replace("package:", "").strip() for pkg in result.splitlines()]
    
    def GetDeviceProperties(self):
        return {
            "Model": self.target.shell("getprop ro.product.model").strip(),
            "Version": self.target.shell("getprop ro.build.version.release").strip(),
            "Resolution": self.target.shell("wm size").strip(),
            "DPI": self.target.shell("wm density").strip()
        }
    
    def GetBatteryInfo(self):
        raw = self.target.shell("dumpsys battery")
        info = {}
        for line in raw.splitlines():
            line = line.strip() 
            if not line:
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip() if value.strip() else None
                info[key] = value
            else:
                info[line.strip()] = None

        status_map = {
            "1": "Unknown",
            "2": "Charging",
            "3": "Discharging",
            "4": "Not charging",
            "5": "Full"
        }
        health_map = {
            "1": "Unknown",
            "2": "Good",
            "3": "Overheat",
            "4": "Dead",
            "5": "Overvoltage",
            "6": "Failure",
            "7": "Cold"
        }

        if "status" in info:
            info["status"] = status_map.get(info["status"], info["status"])
        if "health" in info:
            info["health"] = health_map.get(info["health"], info["health"])

        return info

    
    def IsDeviceActive(self):
        return self.target.shell("dumpsys power")
    
    def GetDetailedPackageInfo(self, package_name):
        return self.target.shell(f"dumpsys package {package_name}")
    
    def GetNetworkConnectivityInfo(self):
        wifi_info = self.target.shell("dumpsys wifi").splitlines()
        wifi_ssid, wifi_rssi = None, None

        for line in wifi_info:
            if "SSID:" in line and not wifi_ssid:
                wifi_ssid = line.split("SSID:")[-1].strip().strip('"')
            if "RSSI:" in line and not wifi_rssi:
                wifi_rssi = line.split("RSSI:")[-1].strip()

        ip_output = self.target.shell("ip addr show wlan0 || ip addr show wifi0")
        ip_addr = None
        for line in ip_output.splitlines():
            if "inet " in line:
                ip_addr = line.strip().split()[1]
                break

        sim_info = self.target.shell("getprop gsm.operator.alpha").strip()

        return {
            "wifi_ssid": wifi_ssid or "Unknown",
            "wifi_rssi": wifi_rssi or "Unknown",
            "ip_addr": ip_addr or "Not Connected",
            "sim_carrier": sim_info or "No SIM"
        }
    
    def GetCallState(self):
        raw = self.target.shell("dumpsys telecom")
        call = {"state": "IDLE", "number": None, "contact": None}

        if "ACTIVE" in raw:
            call["state"] = "ACTIVE"
        elif "DIALING" in raw:
            call["state"] = "DIALING"
        elif "RINGING" in raw:
            call["state"] = "RINGING"
        elif "DISCONNECTED" in raw:
            call["state"] = "DISCONNECTED"

        m_num = re.search(r"handle \(PHONE\): tel:(\+?\d+)", raw)
        if m_num:
            call["number"] = m_num.group(1)

        return call
    
    def GetNotifications(self):
        raw = self.target.shell("dumpsys notification --noredact")
        notifs = []
        
        current_pkg = None
        for line in raw.splitlines():
            line = line.strip()
            
            if "NotificationRecord(" in line:
                pkg_match = re.search(r'pkg=([^,\s]+)', line)
                if pkg_match:
                    current_pkg = pkg_match.group(1)
                    notifs.append(current_pkg)
            
            elif "package=" in line:
                pkg_match = re.search(r'package=([^,\s]+)', line)
                if pkg_match:
                    notifs.append(pkg_match.group(1))
            
            elif "pkg=" in line and "NotificationRecord" not in line:
                pkg_match = re.search(r'pkg=([^,\s]+)', line)
                if pkg_match:
                    notifs.append(pkg_match.group(1))
        
        if len(notifs) < 3: 
            try:
                alt_raw = self.target.shell("dumpsys notification")
                for line in alt_raw.splitlines():
                    line = line.strip()
                    if "user=" in line and "pkg=" in line:
                        pkg_match = re.search(r'pkg=([^,\s]+)', line)
                        if pkg_match:
                            notifs.append(pkg_match.group(1))
            except:
                pass
        
        unique_notifs = list(set([pkg for pkg in notifs if pkg and not pkg.startswith('android.')]))
        
        return {
            "active_notifications": unique_notifs,
            "total_count": len(unique_notifs)
        }
    
    def GetLocation(self):
        raw = self.target.shell("dumpsys location")
        loc = {
            "lat": None, 
            "lon": None, 
            "provider": None, 
            "accuracy": None,
            "timestamp": None,
            "status": "Checking location...",
            "permission_status": "Unknown",
            "status": "No location available"
        }

        try:
            perm_output = self.target.shell("dumpsys package com.android.providers.location")
            if "android.permission.ACCESS_FINE_LOCATION: granted=true" in perm_output or \
               "android.permission.ACCESS_COARSE_LOCATION: granted=true" in perm_output:
                loc["permission_status"] = "System location permission granted"
            else:
                loc["permission_status"] = "System location permission unclear"
            
            location_mode = self.target.shell("settings get secure location_mode").strip()
            if location_mode in ["1", "2", "3"]:
                loc["debug_info"].append(f"Location mode: {location_mode}")
            else:
                loc["status"] = "Location services may be disabled"
                loc["debug_info"].append(f"Location mode: {location_mode}")
        except Exception as e:
            loc["debug_info"].append(f"Permission check error: {str(e)}")
        
        location_commands = [
            "dumpsys location",
            "dumpsys location_manager", 
            "dumpsys locationpolicy",
            "dumpsys gps"
        ]
        
        for cmd in location_commands:
            try:
                raw = self.target.shell(cmd)
                if raw and len(raw) > 50:
                    loc["debug_info"].append(f"Tried {cmd}: Got {len(raw)} chars")
                    
                    location_patterns = [
                        (r"fused.*?Location\[([0-9.\-]+),([0-9.\-]+)", "fused"),
                        (r"fused.*?lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "fused"),
                        (r"gps.*?Location\[([0-9.\-]+),([0-9.\-]+)", "gps"),
                        (r"gps.*?lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "gps"),
                        (r"network.*?Location\[([0-9.\-]+),([0-9.\-]+)", "network"),
                        (r"network.*?lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "network"),
                        (r"last.*?known.*?Location\[([0-9.\-]+),([0-9.\-]+)", "last_known"),
                        (r"last.*?lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "last_known"),
                        (r"Location\[([0-9.\-]+),([0-9.\-]+)", "generic"),
                        (r"lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "generic"),
                        (r"latitude[=/:]([0-9.\-]+).*?longitude[=/:]([0-9.\-]+)", "generic"),
                        (r"coordinates.*?([0-9.\-]+),([0-9.\-]+)", "coordinates"),
                        (r"position.*?([0-9.\-]+),([0-9.\-]+)", "position")
                    ]
                    
                    for pattern, provider_type in location_patterns:
                        matches = re.finditer(pattern, raw, re.IGNORECASE | re.DOTALL)
                        for match in matches:
                            try:
                                lat = float(match.group(1))
                                lon = float(match.group(2))
                                
                                if -90 <= lat <= 90 and -180 <= lon <= 180 and (abs(lat) > 0.001 or abs(lon) > 0.001):
                                    loc["lat"] = lat
                                    loc["lon"] = lon
                                    loc["provider"] = provider_type
                                    loc["status"] = f"Location found via {cmd}"
                                    
                                    section_start = max(0, match.start() - 200)
                                    section_end = min(len(raw), match.end() + 200)
                                    section = raw[section_start:section_end]
                                    
                                    acc_match = re.search(r"acc[uracy]*[=/:]([0-9.]+)", section, re.IGNORECASE)
                                    if acc_match:
                                        loc["accuracy"] = float(acc_match.group(1))
                                    
                                    time_patterns = [
                                        r"time[=/:]([0-9]{10,13})",
                                        r"timestamp[=/:]([0-9]{10,13})",
                                        r"age[=/:]([0-9]+)"
                                    ]
                                    for time_pattern in time_patterns:
                                        time_match = re.search(time_pattern, section, re.IGNORECASE)
                                        if time_match:
                                            loc["timestamp"] = int(time_match.group(1))
                                            break
                                    
                                    return loc
                                    
                            except (ValueError, IndexError) as e:
                                loc["debug_info"].append(f"Parse error in {provider_type}: {str(e)}")
                                continue
                else:
                    loc["debug_info"].append(f"Tried {cmd}: No substantial output")
            except Exception as e:
                loc["debug_info"].append(f"Error with {cmd}: {str(e)}")
        
        if loc["lat"] is None:
            if "Location mode: 0" in loc.get("debug_info", []):
                loc["status"] = "Location services are disabled on device"
            elif loc["permission_status"] == "System location permission unclear":
                loc["status"] = "Location permission may be denied or location services disabled"
            else:
                loc["status"] = "No location data available despite permissions"
        
        return loc
    
    def GetLocation(self):
        """
        Comprehensive location detection with permission checks and multiple methods
        """
        loc = {
            "lat": None, 
            "lon": None, 
            "provider": None, 
            "accuracy": None,
            "timestamp": None,
            "status": "Checking location...",
            "permission_status": "Unknown",
            "debug_info": []
        }
        
        try:
            perm_output = self.target.shell("dumpsys package com.android.providers.location")
            if "android.permission.ACCESS_FINE_LOCATION: granted=true" in perm_output or \
            "android.permission.ACCESS_COARSE_LOCATION: granted=true" in perm_output:
                loc["permission_status"] = "System location permission granted"
            else:
                loc["permission_status"] = "System location permission unclear"
            
            location_mode = self.target.shell("settings get secure location_mode").strip()
            if location_mode in ["1", "2", "3"]: 
                loc["debug_info"].append(f"Location mode: {location_mode}")
            else:
                loc["status"] = "Location services may be disabled"
                loc["debug_info"].append(f"Location mode: {location_mode}")
        except Exception as e:
            loc["debug_info"].append(f"Permission check error: {str(e)}")
        
        location_commands = [
            "dumpsys location",
            "dumpsys location_manager", 
            "dumpsys locationpolicy",
            "dumpsys gps"
        ]
        
        for cmd in location_commands:
            try:
                raw = self.target.shell(cmd)
                if raw and len(raw) > 50:
                    loc["debug_info"].append(f"Tried {cmd}: Got {len(raw)} chars")
                    
                    location_patterns = [
                        # Fused location (Google Play Services)
                        (r"fused.*?Location\[([0-9.\-]+),([0-9.\-]+)", "fused"),
                        (r"fused.*?lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "fused"),
                        
                        # GPS provider
                        (r"gps.*?Location\[([0-9.\-]+),([0-9.\-]+)", "gps"),
                        (r"gps.*?lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "gps"),
                        
                        # Network provider  
                        (r"network.*?Location\[([0-9.\-]+),([0-9.\-]+)", "network"),
                        (r"network.*?lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "network"),
                        
                        # Last known location
                        (r"last.*?known.*?Location\[([0-9.\-]+),([0-9.\-]+)", "last_known"),
                        (r"last.*?lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "last_known"),
                        
                        # Generic patterns
                        (r"Location\[([0-9.\-]+),([0-9.\-]+)", "generic"),
                        (r"lat[=/:]([0-9.\-]+).*?lng[=/:]([0-9.\-]+)", "generic"),
                        (r"latitude[=/:]([0-9.\-]+).*?longitude[=/:]([0-9.\-]+)", "generic"),
                        
                        # Coordinate patterns
                        (r"coordinates.*?([0-9.\-]+),([0-9.\-]+)", "coordinates"),
                        (r"position.*?([0-9.\-]+),([0-9.\-]+)", "position")
                    ]
                    
                    for pattern, provider_type in location_patterns:
                        matches = re.finditer(pattern, raw, re.IGNORECASE | re.DOTALL)
                        for match in matches:
                            try:
                                lat = float(match.group(1))
                                lon = float(match.group(2))
                                
                                if -90 <= lat <= 90 and -180 <= lon <= 180 and (abs(lat) > 0.001 or abs(lon) > 0.001):
                                    loc["lat"] = lat
                                    loc["lon"] = lon
                                    loc["provider"] = provider_type
                                    loc["status"] = f"Location found via {cmd}"
                                    
                                    section_start = max(0, match.start() - 200)
                                    section_end = min(len(raw), match.end() + 200)
                                    section = raw[section_start:section_end]
                                    
                                    acc_match = re.search(r"acc[uracy]*[=/:]([0-9.]+)", section, re.IGNORECASE)
                                    if acc_match:
                                        loc["accuracy"] = float(acc_match.group(1))
                                    
                                    time_patterns = [
                                        r"time[=/:]([0-9]{10,13})",  
                                        r"timestamp[=/:]([0-9]{10,13})",
                                        r"age[=/:]([0-9]+)"  
                                    ]
                                    for time_pattern in time_patterns:
                                        time_match = re.search(time_pattern, section, re.IGNORECASE)
                                        if time_match:
                                            loc["timestamp"] = int(time_match.group(1))
                                            break
                                    
                                    return loc
                                    
                            except (ValueError, IndexError) as e:
                                loc["debug_info"].append(f"Parse error in {provider_type}: {str(e)}")
                                continue
                else:
                    loc["debug_info"].append(f"Tried {cmd}: No substantial output")
            except Exception as e:
                loc["debug_info"].append(f"Error with {cmd}: {str(e)}")
      
        if loc["lat"] is None:
            try:
                props = self.target.shell("getprop | grep -i location")
                if props:
                    loc["debug_info"].append(f"Location props: {len(props)} chars")
                
                providers = self.target.shell("settings get secure location_providers_allowed").strip()
                if providers and providers != "null":
                    loc["debug_info"].append(f"Allowed providers: {providers}")
                
            except Exception as e:
                loc["debug_info"].append(f"Properties check error: {str(e)}")
        
        if loc["lat"] is None:
            try:
                activity_output = self.target.shell("dumpsys activity broadcasts | grep -i location")
                if activity_output:
                    loc["debug_info"].append("Found location-related broadcasts")
            except:
                pass
        
        if loc["lat"] is None:
            if "0" in loc.get("debug_info", []): 
                loc["status"] = "Location services are disabled on device"
            elif loc["permission_status"] == "System location permission unclear":
                loc["status"] = "Location permission may be denied or location services disabled"
            else:
                loc["status"] = "No location data available despite permissions"
        
        return loc
    
    def CheckLocationPermissions(self):
        """
        Separate method to thoroughly check location permissions
        """
        permission_info = {
            "location_services_enabled": False,
            "location_mode": "Unknown",
            "apps_with_location_permission": [],
            "system_location_permission": "Unknown"
        }
        
        try:
            location_mode = self.target.shell("settings get secure location_mode").strip()
            mode_names = {
                "0": "Off",
                "1": "Device only (GPS)",
                "2": "Battery saving (Network)",
                "3": "High accuracy (GPS + Network)"
            }
            permission_info["location_mode"] = mode_names.get(location_mode, f"Unknown ({location_mode})")
            permission_info["location_services_enabled"] = location_mode in ["1", "2", "3"]
            
            packages = self.target.shell("pm list packages | head -20").splitlines() 
            for line in packages:
                if "package:" in line:
                    package = line.replace("package:", "").strip()
                    try:
                        perm_check = self.target.shell(f"dumpsys package {package} | grep -A5 -B5 location")
                        if "ACCESS_FINE_LOCATION" in perm_check and "granted=true" in perm_check:
                            permission_info["apps_with_location_permission"].append(package)
                    except:
                        continue
                    
                    if len(permission_info["apps_with_location_permission"]) >= 5: 
                        break
            
        except Exception as e:
            permission_info["error"] = str(e)
        
        return permission_info

    def _parse_media_sessions(self, raw_media):
        sessions = []
        chunks = raw_media.split("Sessions Stack")
        for chunk in chunks:
            info = {
                "package": None,
                "state": "UNKNOWN",
                "position": None,
                "speed": None,
                "title": None,
                "artist": None,
                "album": None
            }

            m_pkg = re.search(r'package=([\w\.]+)', chunk)
            if m_pkg:
                info["package"] = m_pkg.group(1)

            m_state = re.search(r'state=PlaybackState \{state=(\d+)', chunk)
            if m_state:
                state_code = m_state.group(1)
                state_map = {"1": "STOPPED", "2": "PAUSED", "3": "PLAYING"}
                info["state"] = state_map.get(state_code, f"STATE_{state_code}")

            m_pos = re.search(r'position=(\d+)', chunk)
            if m_pos:
                info["position"] = int(m_pos.group(1))

            m_spd = re.search(r'speed=([0-9.]+)', chunk)
            if m_spd:
                info["speed"] = float(m_spd.group(1))

            m_meta = re.search(r'metadata:.*description=(.*)', chunk)
            if m_meta:
                description = m_meta.group(1).strip()
                parts = [p.strip() for p in description.split(",")]
                if parts:
                    info["title"] = parts[0]
                if len(parts) > 1:
                    info["artist"] = parts[1]
                if len(parts) > 2:
                    info["album"] = ", ".join(parts[2:])

            if info["package"]:
                sessions.append(info)

        return sessions
    
    def TryEnableLocationServices(self):
        """
        Attempt to enable location services (requires user interaction on newer Android)
        """
        try:
            current_mode = self.target.shell("settings get secure location_mode").strip()
            print(f"Current location mode: {current_mode}")
            
            if current_mode == "0":
                print("Attempting to enable location services...")
                
                result = self.target.shell("settings put secure location_mode 3")
                
                new_mode = self.target.shell("settings get secure location_mode").strip()
                if new_mode != "0":
                    print(f"✅ Location mode changed to: {new_mode}")
                    return True
                else:
                    print("❌ Could not enable location services. Manual intervention required.")
                    print("Please enable Location Services in Settings > Location")
                    return False
            else:
                print(f"Location services already enabled (mode: {current_mode})")
                return True
                
        except Exception as e:
            print(f"Error trying to enable location: {e}")
            return False



    def GetForegroundAppDetailed(self):
        app_info = {"package": None, "activity": None, "inferred_state": "Unknown"}

        act_dump = self.target.shell("dumpsys activity activities")
        resumed_line = None
        for line in act_dump.splitlines():
            if "mResumedActivity" in line or "mResumedActivities" in line:
                resumed_line = line.strip()
                break
            if "topResumedActivity" in line.lower():
                resumed_line = line.strip()
                break

        if resumed_line:
            for token in resumed_line.split():
                if '/' in token:
                    try:
                        pkg, activity = token.split('/', 1)
                    except ValueError:
                        continue
                    pkg = pkg.strip()
                    activity = activity.strip().strip('}').strip(',')
                    app_info["package"] = pkg
                    app_info["activity"] = activity
                    act_lower = activity.lower()
                    if any(x in act_lower for x in ("watch", "video", "player", "playback")):
                        app_info["inferred_state"] = "Watching Video"
                    elif any(x in act_lower for x in ("music", "audio", "nowplaying", "player")):
                        app_info["inferred_state"] = "Listening to Music"
                    elif any(x in act_lower for x in ("chat", "conversation", "message")):
                        app_info["inferred_state"] = "Chatting"
                    elif any(x in act_lower for x in ("home", "shell", "launcher")):
                        app_info["inferred_state"] = "Browsing/Home Screen"
                    else:
                        app_info["inferred_state"] = "Using App"
                    break

        raw_media = self.target.shell("dumpsys media_session")
        sessions = self._parse_media_sessions(raw_media)

        fg_pkg = app_info.get("package")
        fg_session = None
        background_sessions = []
        for s in sessions:
            if fg_pkg and s.get("package"):
                if pkg == fg_pkg or pkg.startswith(fg_pkg + ":"):
                    if fg_session is None:
                        fg_session = s
                    else:
                        if fg_session.get("state") != "PLAYING" and s.get("state") == "PLAYING":
                            fg_session = s
            else:
                if s.get("package"):
                    background_sessions.append(s)

        if fg_session:
            if fg_session.get("state") == "PLAYING":
                if app_info["inferred_state"] in ("Browsing/Home Screen", "Using App"):
                    app_info["inferred_state"] = "Playing (foreground app)"
                else:
                    app_info["inferred_state"] = f"{app_info['inferred_state']} (playing)"
            app_info["media_session"] = fg_session

        playing_bg = [s for s in background_sessions if s.get("state") == "PLAYING"]
        if playing_bg:
            app_info["background_media"] = [
                {"package": s.get("package"), "state": s.get("state"),
                "title": s.get("title"), "artist": s.get("artist"), "position": s.get("position")}
                for s in playing_bg
            ]

        return app_info

    def GetStorageInfo(self):
        raw = self.target.shell("df -h /data")
        parts = raw.splitlines()
        if len(parts) > 1:
            cols = parts[1].split()
            return {"Total": cols[1], "Used": cols[2], "Available": cols[3], "Usage": cols[4]}
        return {}
    
    def GetScreenState(self):
        output = self.target.shell("dumpsys window")
        state = "Unknown"

        for line in output.splitlines():
            line = line.strip().lower()
            if "mDreamingLockscreen" in line or "mShowingLockscreen" in line:
                if "true" in line:
                    state = "Locked"
                    break
                elif "false" in line:
                    state = "Unlocked"
                    break

        if state == "Unknown":
            power = self.target.shell("dumpsys power")
            if "mHoldingDisplaySuspendBlocker=true" in power or "mWakefulness=Awake" in power:
                state = "Unlocked"
            else:
                state = "Locked"

        return state
    
    def GetMemoryInfo(self):
        return self.target.shell("dumpsys meminfo").strip()
    
    def GetTopProcesses(self):
        return self.target.shell("top -n 1 -b").strip()
    

    def GetUserRunningApps(self):
        activities_output = self.target.shell("dumpsys activity activities")
    
        user_apps = set()
        for line in activities_output.splitlines():
            line = line.strip()
            if "Hist" in line or "mResumedActivity" in line:
                parts = line.split()
                for part in parts:
                    if "/" in part and "." in part:
                        pkg = part.split("/")[0]
                        user_apps.add(pkg)

        recents_output = self.target.shell("dumpsys activity recents")
        for line in recents_output.splitlines():
            line = line.strip()
            if "Recent #".lower() in line.lower():
                if "A=" in line:
                    pkg = line.split("A=")[1].split()[0]
                    user_apps.add(pkg)

        return list(user_apps)
    
    def CollectSnapshot(self):
        return {
            "TimeStamp" : self.target.shell("date '+%Y-%m-%d %H:%M:%S'").strip(),
            "Device": self.GetDeviceProperties(),
            "Battery": self.GetBatteryInfo(),
            "ScreenState": self.GetScreenState(),
            "Network": self.GetNetworkConnectivityInfo(),
            "Storage": self.GetStorageInfo(),
            "Recent Apps" : self.GetUserRunningApps(),
            "On Screen Running App" : self.GetForegroundAppDetailed(),
            "Trace" : self.GetActivityTrace()
        }
    
    def GetActivityTrace(self):
        trace = {
            "Call": self.GetCallState(),
            "Messaging": self.GetNotifications(),
            "Media": self.GetForegroundAppDetailed(), 
            "Location": self.GetLocation()
        }
        return trace

class SaveData:
    def __init__(self ,):
        self.file_location = "PhoneDataCollector/DataCollected/"
        os.makedirs(self.file_location, exist_ok=True)

    def SaveAsJson(self,data , name = "phone_data"):
        now = datetime.now()
        date = now.strftime("%Y-%m-%d")
        time = now.strftime("%H-%M-%S")
        file_name = f"{name}_{date}_{time}.json"

        file_path = os.path.join(self.file_location, file_name)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(f"✅ Data saved successfully: {file_path}")
        except Exception as e:
            print(f"❌ Error saving data: {e}")

def main():
    pdc = PhoneDataCollector()
    phone_data = pdc.CollectSnapshot()
    
    saver = SaveData()
    saver.SaveAsJson(phone_data, "phone_data")
    # saver.SaveAsJson(pdc.GetUserRunningApps() , "running_apps")



if __name__ == "__main__":
    main()
