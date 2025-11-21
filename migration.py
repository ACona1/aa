import ftplib
import json
import requests
import time
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

# عدد العمليات المتزامنة (طلبك 20)
MAX_WORKERS = 20 

# ==========================================
# 🛠️ HELPER FUNCTIONS
# ==========================================

def connect_ftp():
    """Establishes a fresh FTP connection."""
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
        r = requests.get(api_url).json()
        if r['status'] == 200 and 'result' in r:
            return r['result']['id'], r['result'].get('folderid')
    except:
        pass
    return None, None

def wait_for_completion(remote_id, log_prefix=""):
    api_url = f"https://api.streamtape.com/remotedl/status?login={ST_LOGIN}&key={ST_KEY}&id={remote_id}"
    
    # لا نطبع نقاط كثيرة عشان الـ terminal ميتزحمش مع 20 عملية
    # print(f"{log_prefix} ⏳ Transferring...", end="", flush=True)
    
    retries = 0
    max_retries = 120 
    
    while retries < max_retries:
        try:
            r = requests.get(api_url).json()
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
        r = requests.get(api_url).json()
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
        r = requests.post(url, files=files, headers=headers)
        return r.json().get('downloadUrl')
    except:
        return None

# ==========================================
# 🧠 CORE LOGIC (PER FOLDER)
# ==========================================

def process_single_folder(folder_name):
    """
    هذه الدالة تقوم بمعالجة مجلد واحد بالكامل.
    تفتح FTP فقط عند القراءة والكتابة، وتغلقه أثناء الانتظار.
    """
    log_prefix = f"[{folder_name}]"
    print(f"{log_prefix} 🚀 Started processing...")

    # ---------------------------------------------------------
    # PHASE 1: READ DATA (Connect FTP -> Read -> Disconnect)
    # ---------------------------------------------------------
    playlist_data = []
    vtt_files_data = {} # Store filename: content
    
    try:
        ftp = connect_ftp()
        try:
            ftp.cwd(f"/{REMOTE_PATH}/{folder_name}")
            files_in_folder = ftp.nlst()
            
            # 1. Read Playlist
            if "playlist.json" in files_in_folder:
                bio = BytesIO()
                ftp.retrbinary("RETR playlist.json", bio.write)
                try:
                    playlist_data = json.loads(bio.getvalue().decode('utf-8'))
                except:
                    print(f"{log_prefix} ❌ Invalid JSON.")

            # 2. Read VTT Files Content
            vtt_files_list = [f for f in files_in_folder if f.endswith('.vtt')]
            for vf in vtt_files_list:
                bio_vtt = BytesIO()
                ftp.retrbinary(f"RETR {vf}", bio_vtt.write)
                vtt_files_data[vf] = bio_vtt.getvalue().decode('utf-8')

        finally:
            ftp.quit() # 🔥 IMPORTANT: Close connection fast!
    except Exception as e:
        print(f"{log_prefix} ❌ Error reading folder: {e}")
        return

    # ---------------------------------------------------------
    # PHASE 2: PROCESSING (HTTP ONLY - NO FTP)
    # ---------------------------------------------------------
    
    # A. Process Videos
    new_playlist = []
    playlist_changed = False
    
    for idx, item in enumerate(playlist_data):
        link = item.get('video')
        if "streamtape" in link:
            new_playlist.append(item)
            continue

        safe_folder_name = folder_name.replace(" ", "_")
        desired_filename = f"{safe_folder_name}_E{str(idx+1).zfill(2)}.mp4"
        
        print(f"{log_prefix} 🔄 Processing Video: {desired_filename}")
        
        remote_id, folder_dest_id = add_remote_upload(link, desired_filename)
        
        success = False
        if remote_id:
            if wait_for_completion(remote_id, log_prefix):
                time.sleep(1) # Short wait
                final_link = get_real_file_link(desired_filename, folder_dest_id)
                if final_link:
                    new_playlist.append({"video": final_link})
                    playlist_changed = True
                    success = True
                    print(f"{log_prefix} ✅ Video Done: {desired_filename}")

        if not success:
            print(f"{log_prefix} ❌ Video Failed: {desired_filename}")
            new_playlist.append(item)

    # B. Process Subtitles
    subtitle_playlist = []
    subtitle_changed = False
    
    if vtt_files_data:
        print(f"{log_prefix} 📝 Processing {len(vtt_files_data)} subtitles...")
        # Sort keys to maintain order
        for vtt_name in sorted(vtt_files_data.keys()):
            content = vtt_files_data[vtt_name]
            cloud_link = upload_subtitle_to_cloud(content.encode('utf-8'), vtt_name)
            if cloud_link:
                subtitle_playlist.append({"video": cloud_link})
                subtitle_changed = True
                # print(f"{log_prefix} ☁️ Sub Uploaded: {vtt_name}")

    # ---------------------------------------------------------
    # PHASE 3: SAVE DATA (Connect FTP -> Write -> Disconnect)
    # ---------------------------------------------------------
    if playlist_changed or subtitle_changed:
        print(f"{log_prefix} 💾 Saving changes to FTP...")
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
                    
                print(f"{log_prefix} ✅ Saved successfully!")
            finally:
                ftp.quit() # 🔥 Close immediately
        except Exception as e:
            print(f"{log_prefix} ❌ Error saving: {e}")
    else:
        print(f"{log_prefix} ℹ️ No changes to save.")

# ==========================================
# 🚀 MAIN PROCESS
# ==========================================

def main():
    print("🔌 Connecting to FTP to list folders...")
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
        print(f"❌ Error listing folders: {e}")
        return

    print(f"📂 Found {len(folders_to_process)} folders.")
    print(f"🚀 Starting ThreadPool with {MAX_WORKERS} workers...")
    print("-" * 40)

    # تشغيل 20 عملية في نفس الوقت
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(process_single_folder, folders_to_process)

    print("\n🏁 All folders processed.")

if __name__ == "__main__":
    main()
