# Third-Party Binaries for Lager Box

This directory structure is used on the box to store third-party binaries and tools that need to be accessible from within the Lager Docker container.

## Directory Structure

```
/home/lagerdata/third_party/
├── customer-binaries/      # Custom binaries provided by customers
│   ├── custom_tool        # Example: custom device management tool
│   ├── my_tool            # Your custom binary
│   └── README.txt         # Documentation for your binaries
│
├── JLink_Linux_V794a_x86_64/  # J-Link debug tools (optional)
│   ├── JLinkGDBServerCLExe
│   ├── JLinkExe
│   └── ...
│
└── README.md              # This file
```

## Customer Binaries Directory

### Purpose
The `customer-binaries/` directory allows you to provide custom executable binaries that will be called from Lager Python scripts via `subprocess.run()`. This is useful for:
- Device-specific management tools
- Custom firmware flashers
- Proprietary testing utilities
- Any Linux binary you need to run from test scripts

### Setup Instructions

1. **Create the directory** (if it doesn't exist):
   ```bash
   mkdir -p /home/lagerdata/third_party/customer-binaries
   ```

2. **Copy your binaries**:
   ```bash
   # From your local machine
   scp my_binary lagerdata@<box-ip>:/home/lagerdata/third_party/customer-binaries/

   # Or on the box directly
   cp /path/to/my_binary /home/lagerdata/third_party/customer-binaries/
   ```

3. **Make binaries executable**:
   ```bash
   chmod +x /home/lagerdata/third_party/customer-binaries/*
   ```

4. **Restart the Lager container** to mount the directory:
   ```bash
   cd ~/box
   ./start_box.sh
   ```

### Container Mounting
When the directory exists, it is automatically mounted to the Lager container at:
- **Host path**: `/home/lagerdata/third_party/customer-binaries/`
- **Container path**: `/home/www-data/customer-binaries/`

The startup script will detect and list all binaries found in this directory.

### Usage in Python Scripts

From any Lager Python implementation script (`cli/impl/*.py`) or box Python code:

```python
import subprocess

# Call your custom binary
result = subprocess.run(
    ['/home/www-data/customer-binaries/custom_tool', '--version'],
    capture_output=True,
    text=True,
    timeout=30
)

if result.returncode == 0:
    print(f"Output: {result.stdout}")
else:
    raise Exception(f"Command failed: {result.stderr}")
```

### Requirements
- **Platform**: Binaries must be Linux x86_64 compatible
- **Permissions**: Must be executable (chmod +x)
- **Dependencies**: If your binary has shared library dependencies, they must be available in the container

### Verification

Check if your binaries are accessible:
```bash
# List mounted binaries
docker exec lager ls -la /home/www-data/customer-binaries

# Test execution
docker exec lager /home/www-data/customer-binaries/my_binary --version
```

## J-Link Directory

The J-Link software is automatically detected and mounted from directories matching `/home/lagerdata/third_party/JLink_*/`. See the [J-Link documentation](https://www.segger.com/downloads/jlink/) for installation instructions.

## Notes

- Changes to binaries require restarting the container (`./start_box.sh`)
- No Docker image rebuild is needed
- The directory is optional - if it doesn't exist, it won't be mounted
- Multiple binaries can coexist in the customer-binaries directory
- File permissions from the host are preserved in the container

## Troubleshooting

**Binary not found:**
```bash
# Check if directory exists and is mounted
docker inspect lager | grep customer-binaries

# Verify binary exists on host
ls -la /home/lagerdata/third_party/customer-binaries/
```

**Permission denied:**
```bash
# Make sure binary is executable
chmod +x /home/lagerdata/third_party/customer-binaries/my_binary
```

**Binary won't execute:**
```bash
# Check if it's the right architecture
file /home/lagerdata/third_party/customer-binaries/my_binary
# Should show: "ELF 64-bit LSB executable, x86-64"

# Check for missing shared libraries
docker exec lager ldd /home/www-data/customer-binaries/my_binary
```

## Example: Custom Binary Setup

```bash
# Copy your binary to box (replace <BOX_IP> with your box's IP address)
scp custom_tool lagerdata@<BOX_IP>:/home/lagerdata/third_party/customer-binaries/

# Make it executable
ssh lagerdata@<BOX_IP> "chmod +x /home/lagerdata/third_party/customer-binaries/custom_tool"

# Restart container
ssh lagerdata@<BOX_IP> "cd ~/box && ./start_box.sh"

# Verify
ssh lagerdata@<BOX_IP> "docker exec lager /home/www-data/customer-binaries/custom_tool --help"
```

Now you can call your custom binary from Lager Python scripts.
