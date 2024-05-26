import os
import sys
import signal
import struct
import zipfile
import hashlib
import json
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)

def getFlag(name, default):
    search = "--%s=" % name
    for x in sys.argv:
        if x.startswith(search):
            return x[len(search):]
    return default

def getHeader(data, header, separator = ":"):
    for x in data.split("\n"):
        splitted = x.strip().split(separator)
        if len(splitted) != 2:
            continue
        key, value = splitted
        if key.lower() == header.lower():
            return value.strip()
    raise Exception("Couldn't find header " + header)

def readClassHeader(zip, path):
    with zip.open(path) as class_data:
        header = class_data.read(4)
        if header != b"\xca\xfe\xba\xbe":
            raise Exception("Magic header of java class is not CAFEBABE?")
        class_data.read(2) # minor_version, we don't care about this
        major_version, = struct.unpack('>H', class_data.read(2))
        return major_version

def getJavaVersion(zip):
    max_version = 0
    for x in zip.namelist():
        if (x.startswith("net/minecraft/") or x.startswith("io/")) and x.endswith(".class"):
            max_version = max(max_version, readClassHeader(zip, x))
    if max_version != 0:
        return max_version
    manifest_data = zip.read("META-INF/MANIFEST.MF").decode()
    main_class_path = getHeader(manifest_data, "Main-Class")
    return readClassHeader(zip, main_class_path.replace(".", "/") + ".class")

def getVersionFromPaperclip(zip):
    try:
        with zip.open("patch.properties") as patch_properties:
            return getHeader(patch_properties.read().decode(), "version", "=")
    except Exception as e:
        logging.debug(f"Error reading patch.properties: {e}")

    try:
        with zip.open("patch.json") as patch_json:
            patch_contents = patch_json.read().decode()
            return json.loads(patch_contents)["version"]
    except Exception as e:
        logging.debug(f"Error reading patch.json: {e}")

    try:
        with zip.open("version.json") as version_json:
            version_contents = version_json.read().decode()
            return json.loads(version_contents)["id"]
    except Exception as e:
        logging.debug(f"Error reading version.json: {e}")

def getPaperRecommendedVersion(zip):
    version = getVersionFromPaperclip(zip)
    if not version:
        return
    splitted = list(map(int, version.split(".")))
    major, minor = [splitted[0], splitted[1]]
    if major >= 1 and minor >= 21:
        return "Java 21"
    if major >= 1 and minor >= 17:
        return "Java 17"
    if major >= 1 and minor >= 16:
        return "Java 16"
    elif major >= 1 and minor >= 12:
        return "Java 11"
    elif major >= 1 and minor >= 8:
        return "Java 8"

def getJavaName(zip):
    try:
        paper_recommended = getPaperRecommendedVersion(zip)
        if paper_recommended:
            logging.debug(f"Detected Paper recommended version: {paper_recommended}")
            return paper_recommended
    except Exception as e:
        logging.error(f"Error detecting Paper recommended version: {e}")

    try:
        major_version = getJavaVersion(zip)
        logging.debug(f"Detected Java major version: {major_version}")
        if major_version >= 65:
            return "Java 21"
        if major_version >= 61:
            return "Java 17"
        if major_version >= 60:
            return "Java 16"
        elif major_version >= 55:
            return "Java 11"
        else:
            return "Java 8"
    except Exception as e:
        logging.error(f"Error detecting Java version: {e}")
        return "Unknown Java Version"

startup = os.getenv("MODIFIED_STARTUP", os.getenv("STARTUP", ""))
def getJarFromStartup():
    splitted = startup.split(" ")
    for x in splitted:
        if x.strip().endswith(".jar"):
            return x.strip()

def replaceStartupWith(entrypoint):
    splitted = startup.split(" ")
    splitted[0] = entrypoint
    return " ".join(splitted)

def interrupt(signum, frame):
    raise Exception("")

def inputWithTimeout(timeout):
    signal.signal(signal.SIGALRM, interrupt)
    signal.alarm(timeout)
    try:
        res = input()
        signal.alarm(0)
        return res
    except:
        signal.alarm(0)
        return None

def getFileChecksum(path):
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        while chunk := f.read(8192):
            file_hash.update(chunk)
        return file_hash.digest()

def readFile(path):
    with open(path, "rb") as f:
        return f.read()

def writeFile(path, data):
    with open(path, "wb") as f:
        f.write(data)

def deleteFile(path):
    if os.path.exists(path):
        os.remove(path)

mode = getFlag("mode", "echo")
if mode not in ["echo", "env"]:
    raise Exception("Unknown mode '%s' passed." % mode)

is_echo = mode == "echo"
is_env = mode == "env"

default = "Java 11"
entrypointMappings = {
    "Java 8": "java8",
    "Java 11": "java11",
    "Java 16": "java16",
    "Java 17": "java17",
    "Java 21": "java21",
}
state_file = "disable_prompt_for_java_version"
save_file = ".docker_overwrite"
def main():
    jar = getJarFromStartup()
    if not jar:
        if is_echo:
            print("No jar detected in startup arguments - not enforcing java.")
        elif is_env:
            print(startup)
        return

    if jar == "quilt-server-launch.jar":
        jar = "server.jar"

    try:
        checksum = getFileChecksum(jar)

        with zipfile.ZipFile(jar, "r") as zip:
            name = getJavaName(zip)
            if not name:
                name = default

            if not os.path.exists(state_file) or readFile(state_file) != checksum:
                if not is_echo:
                    raise Exception("Something went really wrong - prompt should be displayed in echo mode but we're not using that mode???")

                print("Detected initial boot with this jar.")
                initial = True
                timedOut = False
                answer = ""
                while True:
                    if initial:
                        initial = False
                        print("Which java version do you want to use?")
                    else:
                        print("Invalid option '%s' - the only valid options are the following:" % str(answer))

                    print("1) Automatically detected version: '%s'" % name)
                    print("2) Java 8")
                    print("3) Java 11")
                    print("4) Java 16")
                    print("5) Java 17")
                    print("6) Java 21")
                    print("NOTE: this prompt will automatically expire in 30 seconds from inactivity and default to option 1) if nothing is chosen.")

                    answer = inputWithTimeout(30)
                    if answer is None:
                        answer = "1"

                    if answer.endswith(")"):
                        answer = answer[:-1]

                    if answer.isdigit():
                        answer = int(answer)
                        if answer >= 1 and answer <= 6:
                            break

                name = {
                    1: name,
                    2: "Java 8",
                    3: "Java 11",
                    4: "Java 16",
                    5: "Java 17",
                    6: "Java 21",
                }[answer]

                if answer > 1:
                    writeFile(save_file, name.encode())
                else:
                    deleteFile(save_file)

                if not timedOut:
                    writeFile(state_file, checksum)

            if os.path.exists(save_file):
                name = readFile(save_file).decode().strip()

                if name not in entrypointMappings:
                    if is_echo:
                        print("Detected invalid java version '%s', defaulting back to '%s'..." % name % default)
                        print("This choice can be reset by deleting the '%s' file." % state_file)
                    elif is_env:
                        print(replaceStartupWith(entrypointMappings[default]))
                    return

                if is_echo:
                    print("Detected java version being overwritten, using '%s'..." % name)
                    print("This choice can be reset by deleting the '%s' file." % state_file)
                elif is_env:
                    print(replaceStartupWith(entrypointMappings[name]))
                return

            if is_echo:
                print("Detected java version as '%s' automatically." % name)
                print("This choice can be reset by deleting the '%s' file." % state_file)
            elif is_env:
                print(replaceStartupWith(entrypointMappings[name]))
    except Exception as e:
        if is_echo:
            print(f"Couldn't detect jar version - defaulting to '{default}'. Error: {e}")
        elif is_env:
            print(replaceStartupWith(entrypointMappings[default]))

main()
