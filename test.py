import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(
        description="Modify InstallShield 6.31 cabinet files and generate data2.cab"
    )
    parser.add_argument(
        "--iscab",
        default=r"C:\Users\samicrusader\Downloads\InstallShield_Cabinet_File_Viewer",
        help="Path to iscab.exe or directory containing it",
    )
    parser.add_argument(
        "--i6comp",
        default=r"C:\Users\samicrusader\Downloads\i6cmp13b",
        help="Path to i6comp.exe or directory containing it",
    )
    args = parser.parse_args()

    # Resolve executable paths
    iscab_exe = (
        args.iscab
        if args.iscab.endswith(".exe")
        else os.path.join(args.iscab, "iscab.exe")
    )
    i6comp_exe = (
        args.i6comp
        if args.i6comp.endswith(".exe")
        else os.path.join(args.i6comp, "i6comp.exe")
    )

    # Verify prerequisites
    for exe, name in [(iscab_exe, "iscab.exe"), (i6comp_exe, "i6comp.exe")]:
        if not os.path.exists(exe):
            print(f"Error: {name} not found at {exe}")
            sys.exit(1)

    if not os.path.exists("data1.cab"):
        print("Error: data1.cab not found in current directory")
        sys.exit(1)

    # Step 2: Read first 512 bytes of data1.cab
    with open("data1.cab", "rb") as f:
        data1_header = f.read(512)

    if len(data1_header) < 512:
        print("Error: data1.cab is smaller than 512 bytes")
        sys.exit(1)

    # Step 3: Copy files to temp directory within current directory
    temp_dir = tempfile.mkdtemp(dir=".")
    backup_files = ["data1.cab", "data1.hdr", "layout.bin"]

    try:
        for fname in backup_files:
            if os.path.exists(fname):
                shutil.copy2(fname, temp_dir)

        # Step 4: Execute i6comp and capture output
        result = subprocess.run(
            [i6comp_exe, "l", "-d", "data1.cab"],
            capture_output=True,
            text=True,
            check=True,
        )
        i6comp_output = result.stdout

        # Step 5: Extract uint32 from bytes 0x20-0x23 (little-endian)
        uint32_val = struct.unpack("<I", data1_header[0x20:0x24])[0]

        # Step 6: Parse i6comp output to find last Ind value
        matches = re.findall(r"(\d+),\s*\d+", i6comp_output)
        if not matches:
            print("Error: Could not parse Ind values from i6comp output")
            sys.exit(1)
        last_ind = int(matches[-1])

        # Step 7: Create data2.cab
        # 7a: Specific 27-byte header (54 hex chars = 27 bytes)
        # Wait, the hex string "49 53 63 28 0C 60 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 02 00 00 00 00 00 70"
        # Let me count: 49(1) 53(2) 63(3) 28(4) 0C(5) 60(6) 00(7) 01(8) 00(9) 00(10) 00(11) 00(12) 00(13) 00(14) 00(15) 00(16) 00(17) 00(18) 00(19) 00(20) 00(21) 02(22) 00(23) 00(24) 00(25) 00(26) 00(27) 70(28)
        # That's 28 bytes.
        hex_bytes = bytes.fromhex(
            "495363280C6000010000000000000000000000000002000000000070"
        )
        # 7b: uint32 from data1.cab (4 bytes)
        # 7c: last Ind as uint32 (4 bytes)
        # 7d: Zero padding to 512 bytes

        data2_content = bytearray(512)
        pos = 0
        data2_content[pos : pos + len(hex_bytes)] = hex_bytes
        pos += len(hex_bytes)
        data2_content[pos : pos + 4] = struct.pack("<I", uint32_val)
        pos += 4
        data2_content[pos : pos + 4] = struct.pack("<I", last_ind)
        # Remaining bytes are already zero

        with open("data2.cab", "wb") as f:
            f.write(data2_content)

        # Step 8: Execute iscab to generate replace.ini (-lx flag)
        subprocess.run(
            [iscab_exe, "data1.cab", "-ireplace.ini", "-lx"],
            check=True,
            capture_output=True,
        )

        # Step 9: Edit replace.ini - remove entire sections starting with <Support>, <Engine>, <Disk1>
        if not os.path.exists("replace.ini"):
            print("Error: replace.ini was not generated")
            sys.exit(1)

        with open("replace.ini", "r") as f:
            lines = f.readlines()

        forbidden_prefixes = ("<Support>", "<Engine>", "<Disk1>")
        output_lines = []
        skip_section = False

        for line in lines:
            stripped = line.strip()

            # Check if this is a section header
            if stripped.startswith("[") and "]" in stripped:
                # Find the closing bracket to extract section name
                section_end = stripped.find("]")
                if section_end != -1:
                    section_name = stripped[1:section_end]
                    # Check if this section should be skipped
                    skip_section = section_name.startswith(forbidden_prefixes)

            if not skip_section:
                output_lines.append(line)

        with open("replace.ini", "w") as f:
            f.writelines(output_lines)

        # Step 10: Execute iscab to apply changes (-a flag)
        subprocess.run(
            [iscab_exe, "data1.cab", "-ireplace.ini", "-a"],
            check=True,
            capture_output=True,
        )

        # Step 11 & 12: Update data2.cab with bytes from original data1.cab header
        with open("data2.cab", "r+b") as f:
            content = bytearray(f.read())
            # Replace bytes 0x00-0x0B (12 bytes)
            content[0x00:0x0C] = data1_header[0x00:0x0C]
            # Replace bytes 0x60-0x1FF (96-511)
            content[0x60:0x200] = data1_header[0x60:0x200]
            f.seek(0)
            f.write(content)
            f.truncate()

        print("data2.cab created successfully")

    finally:
        # Step 13: Cleanup and restore original files
        #if os.path.exists("replace.ini"):
            #os.remove("replace.ini")

        for fname in backup_files:
            backup_path = os.path.join(temp_dir, fname)
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, fname)

        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
