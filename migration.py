import ftplib
import json
import requests
import time
import random  # <-- مكتبة للاختيار العشوائي
from io import BytesIO
import concurrent.futures

# ==========================================
# ⚙️ SETTINGS
# ==========================================
FTP_HOST = "ftpupload.net"
FTP_USER = "if0_39750276"
FTP_PASS = "r7lKZajudSFef0F"
REMOTE_PATH = "htdocs"

ST_LOGIN = "2e8783677aef747a702a"
ST_KEY = "qlbjQjOB1AizGGe"

MAX_WORKERS = 20 

# ==========================================
# 🌐 PROXY SETTINGS (ضع البروكسيات هنا)
# ==========================================
# الصيغة: "ip:port" أو "user:pass@ip:port"
# يفضل استخدام بروكسيات HTTPS قوية
PROXY_LIST = [
    # أمثلة (استبدلها ببروكسيات حقيقية):
    # "123.45.67.89:8080",
    # "user:pass@192.168.1.1:3128",
]

# تفعيل البروكسي؟ (True/False)
USE_PROXY = False  # <-- اجعلها True لو معاك بروكسيات شغالة

# ==========================================
# 🛠️ HELPER FUNCTIONS
# ==========================================

def get_random_proxy():
    """يختار بروكسي عشوائي ويجهزه لمكتبة requests"""
    if not USE_PROXY or not PROXY_LIST:
        return None
    
    proxy_ip = random.choice(PROXY_LIST)
    return {
        "http": f"http://{proxy_ip}",
        "https": f"http://{proxy_ip}",
    }

def connect_ftp():
    try:
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.encoding = "utf-8" 
        return ftp
    except Exception as e:
        print(f"❌ FTP Connection Error: {e}")
        raise e

def add_remote_upload(url, filename, folder_id=None):
    api_url = f"https://api.streamtape.com/remotedl/add?login={ST_LOGIN}&key={ST_KEY}&url={url}&name={filename}"
    if folder_id:
        api_url += f"&folder={folder_id}"
        
    try:
        # 🔥 إضافة البروكسي هنا
        proxies = get_random_proxy()
        r = requests.get(api_url, proxies=proxies, timeout=15).json()
        
        if r['status'] == 200 and 'result' in r:
            return r['result']['id'], r['result'].get('folderid')
    except:
        pass
    return None, None

def wait_for_completion(remote_id, log_prefix=""):
    api_url = f"https://api.streamtape.com/remotedl/status?login={ST_LOGIN}&key={ST_KEY}&id={remote_id}"
    
    retries = 0
    max_retries = 120 
    
    while retries < max_retries:
        try:
            # 🔥 إضافة البروكسي هنا أيضاً
            proxies = get_random_proxy()
            r = requests.get(api_url, proxies=proxies, timeout=15).json()
            
            result = r['result'].get(str(remote_id))
            
            if result:
                status = result['status']
                if status == 'finished':
                    return True
                elif status in ['downloading', 'new']:
                    time.sleep(5)
                    retries += 1
                else:
                    return False
            else:
                return True 
        except:
            time.sleep(5)
            retries += 1
            
    return False

def get_real_file_link(filename, folder_id):
    folder_param = f"&folder={folder_id}" if folder_id else ""
    api_url = f"https://api.streamtape.com/file/listfolder?login={ST_LOGIN}&key={ST_KEY}{folder_param}"
    
    try:
        proxies = get_random_proxy()
        r = requests.get(api_url, proxies=proxies, timeout=15).json()
        if r['status'] == 200 and 'result' in r:
            files = r['result']['files']
            for f in files:
                if f['name'] == filename:
                    return f"https://streamtape.com/v/{f['linkid']}"
    except:
        pass
    return None

def upload_subtitle_to_cloud(file_content, filename):
    url = "https://tstore.ouim.me/upload"
    headers = {'User-Agent': 'Mozilla/5.0'}
    files = {'file': (filename, file_content, 'text/plain')}
    try:
        proxies = get_random_proxy()
        r = requests.post(url, files=files, headers=headers, proxies=proxies, timeout=20)
        return r.json().get('downloadUrl')
    except:
        return None

# ==========================================
# 🧠 CORE LOGIC (PER FOLDER)
# ==========================================

def process_single_folder(folder_name):
    log_prefix = f"[{folder_name}]"
    print(f"{log_prefix} 🚀 Started processing...")

    playlist_data = []
    vtt_files_data = {} 
    
    # 1. FTP READ (بدون بروكسي طبعاً لأن الـ FTP حساس)
    try:
        ftp = connect_ftp()
        try:
            ftp.cwd(f"/{REMOTE_PATH}/{folder_name}")
            files_in_folder = ftp.nlst()
            
            if "playlist.json" in files_in_folder:
                bio = BytesIO()
                ftp.retrbinary("RETR playlist.json", bio.write)
                try:
                    playlist_data = json.loads(bio.getvalue().decode('utf-8'))
                except:
                    print(f"{log_prefix} ❌ Invalid JSON.")

            vtt_files_list = [f for f in files_in_folder if f.endswith('.vtt')]
            for vf in vtt_files_list:
                bio_vtt = BytesIO()
                ftp.retrbinary(f"RETR {vf}", bio_vtt.write)
                vtt_files_data[vf] = bio_vtt.getvalue().decode('utf-8')

        finally:
            ftp.quit()
    except Exception as e:
        print(f"{log_prefix} ❌ Error reading folder: {e}")
        return

    # 2. PROCESSING (With Proxy Support)
    new_playlist = []
    playlist_changed = False
    
    for idx, item in enumerate(playlist_data):
        link = item.get('video')
        if "streamtape" in link:
            new_playlist.append(item)
            continue

        safe_folder_name = folder_name.replace(" ", "_")
        desired_filename = f"{safe_folder_name}_E{str(idx+1).zfill(2)}.mp4"
        
        print(f"{log_prefix} 🔄 Processing: {desired_filename}")
        
        remote_id, folder_dest_id = add_remote_upload(link, desired_filename)
        
        success = False
        if remote_id:
            if wait_for_completion(remote_id, log_prefix):
                time.sleep(1)
                final_link = get_real_file_link(desired_filename, folder_dest_id)
                if final_link:
                    new_playlist.append({"video": final_link})
                    playlist_changed = True
                    success = True
                    print(f"{log_prefix} ✅ Done: {desired_filename}")

        if not success:
            print(f"{log_prefix} ❌ Failed: {desired_filename}")
            new_playlist.append(item)

    subtitle_playlist = []
    subtitle_changed = False
    
    if vtt_files_data:
        print(f"{log_prefix} 📝 Processing subs...")
        for vtt_name in sorted(vtt_files_data.keys()):
            content = vtt_files_data[vtt_name]
            cloud_link = upload_subtitle_to_cloud(content.encode('utf-8'), vtt_name)
            if cloud_link:
                subtitle_playlist.append({"video": cloud_link})
                subtitle_changed = True

    # 3. FTP SAVE
    if playlist_changed or subtitle_changed:
        print(f"{log_prefix} 💾 Saving...")
        try:
            ftp = connect_ftp()
            try:
                ftp.cwd(f"/{REMOTE_PATH}/{folder_name}")
                
                if playlist_changed:
                    json_bytes = json.dumps(new_playlist, indent=2).encode('utf-8')
                    ftp.storbinary("STOR playlist.json", BytesIO(json_bytes))
                    
                if subtitle_changed:
                    sub_json_bytes = json.dumps(subtitle_playlist, indent=2).encode('utf-8')
                    ftp.storbinary("STOR subtitle.json", BytesIO(sub_json_bytes))
                    
                print(f"{log_prefix} ✅ Saved!")
            finally:
                ftp.quit()
        except Exception as e:
            print(f"{log_prefix} ❌ Error saving: {e}")
    else:
        print(f"{log_prefix} ℹ️ No changes.")

# ==========================================
# 🚀 MAIN
# ==========================================

def main():
    print("🔌 Connecting to FTP...")
    folders_to_process = []
    try:
        ftp = connect_ftp()
        ftp.cwd(REMOTE_PATH)
        all_items = ftp.nlst()
        for item in all_items:
            if item in ['.', '..', 'rclone.conf', 'migration.py']: continue
            folders_to_process.append(item)
        ftp.quit()
    except Exception as e:
        print(f"❌ Error listing: {e}")
        return

    print(f"📂 Found {len(folders_to_process)} folders.")
    print(f"🚀 Starting ThreadPool with {MAX_WORKERS} workers...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(process_single_folder, folders_to_process)

    print("\n🏁 All folders processed.")

if __name__ == "__main__":
    main()
