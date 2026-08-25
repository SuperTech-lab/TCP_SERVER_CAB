
import time
import re
import sys
import ipaddress  
import json

 
TIME_MAX_INACTIVITY = 604800 # 1 week temporary IPs
AUTH_LOG = "/var/log/auth.log"
USER = "admin"
TEMPORARY_IPS_FILE = "temporary_ips.json"
TEMPORARY_IPS = {}

#  RANKS WHITELIST 
RANK_1_START = "192.168.38.1" 
RANK_1_END =  "192.168.38.7" 
RANK_2_START ="192.168.11.120"
RANK_2_END =  "192.168.11.135" 

def is_authorized_ip(ip):
    if is_in_whitelist(ip):
        return True

    if ip in TEMPORARY_IPS:
        return True

    return False

def load_temporary_ips():
    """Load temporary IPs from JSON file."""

    global TEMPORARY_IPS

    try:
        with open(TEMPORARY_IPS_FILE, "r") as file:
            TEMPORARY_IPS = json.load(file)

    except FileNotFoundError:
        TEMPORARY_IPS = {}

    except json.JSONDecodeError:
        TEMPORARY_IPS = {}

def save_temporary_ips():
    """Save temporary IPs to JSON file."""

    with open(TEMPORARY_IPS_FILE, "w") as file:
        json.dump(TEMPORARY_IPS, file, indent=4)

def is_in_whitelist(ip_str):
   # Check if an IP belongs to the WHITELIST.
    try:
        ip = ipaddress.ip_address(ip_str)
        # RANK 1
        r1_inf = ipaddress.ip_address(RANK_1_START)
        r1_sup = ipaddress.ip_address(RANK_1_END)
        if r1_inf <= ip <= r1_sup:
            return True
        
        # RANK 2
        r2_inf = ipaddress.ip_address(RANK_2_START)
        r2_sup = ipaddress.ip_address(RANK_2_END)
        if r2_inf <= ip <= r2_sup:
            return True
        
        # If it is not on the WHITELIST
        return False
    except ValueError:
        return False

def authorize_ip(ip, permanent=False):
    """Register an authorized IP."""
    ip_type = "WHITELIST" if permanent else "TEMPORARY"
    print(f"[GUARD] Authorized {ip_type} IP: {ip}")

def revoke_ip(ip):
    """Remove an expired temporary IP."""
    print(f"[GUARD] Removed expired temporary IP: {ip}")

def monitor_log():
    print("[GUARD] Starting SSH monitor...")
    print("[GUARD] WHITELIST ranges:")
    print(f"   {RANK_1_START} - {RANK_1_END}")
    print(f"   {RANK_2_START} - {RANK_2_END}")
    print(f"[GUARD] Monitoring logins for user '{USER}'")
    load_temporary_ips()
    print(f"[GUARD] Loaded {len(TEMPORARY_IPS)} temporary IPs.")

    try:
        with open(AUTH_LOG, "r") as log:
            # Move to the end of the log file
            log.seek(0, 2)
            
            last_cleanup = time.time()
            
            while True:
                line = log.readline()
                now = time.time()
                
                # 1. Monitor SSH logins
                if line:
                    if f"Accepted password for {USER}" in line:
                        ip_match = re.search(r"from (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
                        if ip_match:
                            incoming_ip = ip_match.group(1)
                            
                            # Register or renew a temporary IP
                            if is_in_whitelist(incoming_ip):
                                authorize_ip(incoming_ip, permanent=True)
                            else:
                                if incoming_ip not in TEMPORARY_IPS:
                                    authorize_ip(incoming_ip, permanent=False)
                                else:
                                    print(f"[GUARD] Temporary IP {incoming_ip} renewed.")

                                TEMPORARY_IPS[incoming_ip] = now
                                save_temporary_ips()

                # 2. Remove expired temporary IPs
                if now - last_cleanup > 60:
                    ips_to_remove = []
                    
                    for ip, last_access in list(TEMPORARY_IPS.items()):
                        if now - last_access > TIME_MAX_INACTIVITY:
                            revoke_ip(ip)
                            ips_to_remove.append(ip)
                    
                    for ip in ips_to_remove:
                        del TEMPORARY_IPS[ip]

                    if ips_to_remove:
                        save_temporary_ips()
                        
                    last_cleanup = now
                
                if not line:
                    time.sleep(0.5)
                    
    except FileNotFoundError:
        print(f"[ERROR] No se encontró el archivo de logs en {AUTH_LOG}.")
        sys.exit(1)
    except PermissionError:
        print("[ERROR] Ejecuta este script con sudo.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[GUARD] Stopping SSH monitor...")
        print("[GUARD] Temporary IP database saved.")

if __name__ == "__main__":
    monitor_log()