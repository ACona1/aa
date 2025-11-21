import ftplib
import json
import requests
import time
from io import BytesIO

# ==========================================
# ⚙️ SETTINGS
# ==========================================
FTP_HOST = "ftpupload.net"
FTP_USER = "if0_39750276"
FTP_PASS = "r7lKZajudSFef0F"
REMOTE_PATH = "htdocs"

ST_LOGIN = "2e8783677aef747a702a"
ST_KEY = "qlbjQjOB1AizGGe"

# ==========================================
# 🛠️ HELPER FUNCTIONS
# ==========================================

def connect_ftp():
    """Establishes a fresh FTP connection."""
    try:
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        # Force UTF-8 encoding to handle spaces/special chars correctly
        ftp.encoding = "utf-8" 
        return ftp
    except Exception as e:
        print(f"❌ FTP Connection Error: {e}")
        raise e

def add_remote_upload(url, filename, folder_id=None):
    # URL encode filename just in case, but requests usually handles it
    api_url = f"https://api.streamtape.com/remotedl/add?login={ST_LOGIN}&key={ST_KEY}&url={url}&name={filename}"
    if folder_id:
        api_url += f"&folder={folder_id}"
        
    try:
        r = requests.get(api_url).json()
        if r['status'] == 200 and 'result' in r:
            return r['result']['id'], r['result'].get('folderid')
        else:
            print(f"      ❌ Failed to add link: {r.get('msg')}")
    except Exception as e:
        print(f"      ❌ Connection error: {e}")
    return None, None

def wait_for_completion(remote_id):
    api_url = f"https://api.streamtape.com/remotedl/status?login={ST_LOGIN}&key={ST_KEY}&id={remote_id}"
    
    print("      ⏳ Transferring...", end="", flush=True)
    
    retries = 0
    max_retries = 120 
    
    while retries < max_retries:
        try:
            r = requests.get(api_url).json()
            result = r['result'].get(str(remote_id))
            
            if result:
                status = result['status']
                
                if status == 'finished':
                    print(" ✅ Upload Complete!")
                    return True
                
                elif status == 'downloading' or status == 'new':
                    print(".", end="", flush=True)
                    time.sleep(5)
                    retries += 1
                else:
                    print(f" ❌ Failed (Status: {status})")
                    return False
            else:
                print(" ⚠️ ID disappeared (Might be finished).")
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
            
            found_file = None
            for f in files:
                # Check exact name match
                if f['name'] == filename:
                    found_file = f
                    break 
            
            if found_file:
                real_link = f"https://streamtape.com/v/{found_file['linkid']}"
                print(f"      🔗 Extracted Real Link: {real_link}")
                return real_link
            
    except Exception as e:
        print(f"      ❌ Error searching for file: {e}")
        
    return None

def upload_subtitle_to_cloud(file_content, filename):
    url = "https://tstore.ouim.me/upload"
    headers = {'User-Agent': 'Mozilla/5.0'}
    # Uploading as text/plain usually works fine for VTT too
    files = {'file': (filename, file_content, 'text/plain')}
    try:
        r = requests.post(url, files=files, headers=headers)
        return r.json().get('downloadUrl')
    except:
        return None

# ==========================================
# 🚀 MAIN PROCESS
# ==========================================

def main():
    print("🔌 Connecting to FTP...")
    try:
        ftp = connect_ftp()
        ftp.cwd(REMOTE_PATH)
        
        print("📂 Listing directory contents...")
        all_items = ftp.nlst()
        
        potential_folders = []
        for item in all_items:
            if item in ['.', '..', 'rclone.conf', 'migration.py']: continue
            potential_folders.append(item)
            
        print(f"📂 Found {len(potential_folders)} items to check.")
        ftp.quit()
        
    except Exception as e:
        print(f"❌ Error Listing Folders: {e}")
        return

    for item_name in potential_folders:
        print(f"\n🔎 Checking: {item_name}")
        
        try:
            ftp = connect_ftp()
            ftp.cwd(f"/{REMOTE_PATH}/{item_name}")
        except:
            print(f"   ℹ️ Skipping (Not a folder or inaccessible).")
            try: ftp.quit() 
            except: pass
            continue

        print(f"📂 Processing Folder: {item_name}")
        
        files_in_folder = ftp.nlst()

        # --- 1. Video Processing ---
        if "playlist.json" in files_in_folder:
            bio = BytesIO()
            ftp.retrbinary("RETR playlist.json", bio.write)
            old_json_content = bio.getvalue().decode('utf-8')
            
            try:
                playlist_data = json.loads(old_json_content)
            except:
                print("   ❌ Invalid JSON in playlist.json")
                playlist_data = []
            
            new_playlist = []
            changed = False
            
            ftp.quit()
            
            for idx, item in enumerate(playlist_data):
                link = item.get('video')
                
                if "streamtape" in link:
                    new_playlist.append(item)
                    continue

                safe_folder_name = item_name.replace(" ", "_")
                desired_filename = f"{safe_folder_name}_E{str(idx+1).zfill(2)}.mp4"
                
                print(f"   🔄 Processing: {desired_filename}")
                
                remote_id, folder_dest_id = add_remote_upload(link, desired_filename)
                
                if remote_id:
                    if wait_for_completion(remote_id):
                        time.sleep(2)
                        final_link = get_real_file_link(desired_filename, folder_dest_id)
                        
                        if final_link:
                            new_playlist.append({"video": final_link})
                            changed = True
                        else:
                            print("      ❌ Uploaded but could not retrieve real link.")
                            new_playlist.append(item)
                    else:
                        new_playlist.append(item)
                else:
                    new_playlist.append(item)

            if changed:
                print("      🔄 Saving playlist.json...")
                try:
                    ftp = connect_ftp()
                    ftp.cwd(f"/{REMOTE_PATH}/{item_name}")
                    
                    json_bytes = json.dumps(new_playlist, indent=2).encode('utf-8')
                    ftp.storbinary("STOR playlist.json", BytesIO(json_bytes))
                    print("✅ playlist.json updated")
                    ftp.quit()
                except Exception as e:
                    print(f"❌ Error saving playlist.json: {e}")

            try:
                ftp = connect_ftp()
                ftp.cwd(f"/{REMOTE_PATH}/{item_name}")
            except:
                pass

        # --- 2. Subtitle Processing (VTT Direct Upload) ---
        try:
             files_in_folder = ftp.nlst()
        except:
             try:
                 ftp = connect_ftp()
                 ftp.cwd(f"/{REMOTE_PATH}/{item_name}")
                 files_in_folder = ftp.nlst()
             except:
                 files_in_folder = []

        vtt_files = [f for f in files_in_folder if f.endswith('.vtt')]
        if vtt_files:
            print(f"📝 Processing {len(vtt_files)} subtitles (Direct VTT)...")
            vtt_files.sort()
            subtitle_playlist = []
            
            for vtt_file in vtt_files:
                bio = BytesIO()
                ftp.retrbinary(f"RETR {vtt_file}", bio.write)
                vtt_content = bio.getvalue().decode('utf-8')
                
                # ⚠️ CHANGE: Upload VTT content directly without conversion
                cloud_link = upload_subtitle_to_cloud(vtt_content.encode('utf-8'), vtt_file)
                
                if cloud_link:
                    subtitle_playlist.append({"video": cloud_link})
                    print(f"   ☁️ Uploaded: {vtt_file}")
            
            if subtitle_playlist:
                sub_json_bytes = json.dumps(subtitle_playlist, indent=2).encode('utf-8')
                ftp.storbinary("STOR subtitle.json", BytesIO(sub_json_bytes))
                print("✅ subtitle.json created")

        try: ftp.quit()
        except: pass

    print("\n🏁 All Done.")

if __name__ == "__main__":
    main()
