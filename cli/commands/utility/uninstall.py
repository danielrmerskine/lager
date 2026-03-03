# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""
    lager.commands.utility.uninstall

    Uninstall Lager box code from a box
"""
import click
import subprocess
import ipaddress
from ...box_storage import get_box_ip, get_box_user


@click.command()
@click.pass_context
@click.option("--box", default=None, help="Box name (uses stored IP and username)")
@click.option("--ip", default=None, help="Target box IP address")
@click.option("--user", default=None, help="SSH username (default: lagerdata, or stored username if using --box)")
@click.option("--keep-config", is_flag=True, help="Keep /etc/lager directory (saved nets, etc.)")
@click.option("--keep-docker-images", is_flag=True, help="Keep Docker images (only remove containers)")
@click.option("--all", "remove_all", is_flag=True, help="Remove everything including udev rules, sudoers, third_party, and legacy deploy key")
@click.option("--yes", is_flag=True, help="Skip confirmation prompts")
def uninstall(ctx, box, ip, user, keep_config, keep_docker_images, remove_all, yes):
    """
    Uninstall Lager box code from a box.
    """
    # 1. Resolve box name to IP and username if --box is provided
    if box and ip:
        click.secho("Error: Cannot specify both --box and --ip", fg='red', err=True)
        ctx.exit(1)

    if box:
        # Look up IP from box storage
        stored_ip = get_box_ip(box)
        if not stored_ip:
            click.secho(f"Error: Box '{box}' not found in configuration", fg='red', err=True)
            click.secho("Use 'lager boxes' to see available boxes, or use --ip to specify directly.", fg='yellow', err=True)
            ctx.exit(1)
        ip = stored_ip

        # Look up username from box storage (if not explicitly provided)
        if user is None:
            stored_user = get_box_user(box)
            user = stored_user or "lagerdata"
    elif ip is None:
        click.secho("Error: Either --box or --ip is required", fg='red', err=True)
        ctx.exit(1)
    else:
        # Default username if not provided
        if user is None:
            user = "lagerdata"

    # 2. Validate IP address
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        click.secho(f"Error: '{ip}' is not a valid IP address", fg='red', err=True)
        ctx.exit(1)

    ssh_host = f"{user}@{ip}"

    # 3. Check SSH connectivity (with password fallback)
    click.echo(f"Checking SSH connectivity to {ssh_host}...")
    use_interactive_ssh = False
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", ssh_host, "echo ok"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            # SSH keys not configured - offer password authentication
            click.secho("SSH keys not configured", fg='yellow')
            click.echo()
            click.echo("SSH key authentication is not set up for this box.")
            click.echo("You can either:")
            click.echo(f"  1. Enter your password now (will be prompted for each SSH command)")
            click.echo(f"  2. Set up SSH keys first with: ssh-copy-id {ssh_host}")
            click.echo()

            if yes or click.confirm("Would you like to continue with password authentication?"):
                click.echo()
                click.echo("Please enter your password to verify connectivity:")
                test_result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=10", "-o", "NumberOfPasswordPrompts=1",
                     ssh_host, "echo ok"],
                    timeout=60
                )
                if test_result.returncode != 0:
                    click.secho("Error: Password authentication failed", fg='red', err=True)
                    click.echo("Please verify your password and try again.", err=True)
                    ctx.exit(1)
                click.secho("Password authentication successful!", fg='green')
                use_interactive_ssh = True
            else:
                click.secho("Uninstall cancelled.", fg='yellow')
                ctx.exit(0)
        else:
            click.secho("SSH connection OK", fg='green')
    except subprocess.TimeoutExpired:
        click.secho(f"Error: SSH connection to {ssh_host} timed out", fg='red', err=True)
        click.secho("Possible causes:", err=True)
        click.secho("  - Box is powered off or unreachable", err=True)
        click.secho("  - Network connection issues", err=True)
        click.secho("  - Firewall blocking SSH (port 22)", err=True)
        ctx.exit(1)
    except FileNotFoundError:
        click.secho("Error: SSH command not found", fg='red', err=True)
        click.secho("Please install OpenSSH client:", err=True)
        import platform
        if platform.system() == "Darwin":
            click.secho("  macOS: SSH should be pre-installed. Check your PATH.", err=True)
        elif platform.system() == "Windows":
            click.secho("  Windows: Install OpenSSH via Settings > Apps > Optional Features", err=True)
        else:
            click.secho("  Linux: sudo apt install openssh-client (Debian/Ubuntu)", err=True)
            click.secho("         sudo dnf install openssh-clients (Fedora/RHEL)", err=True)
        ctx.exit(1)
    except Exception as e:
        error_str = str(e)
        click.secho(f"Error: {e}", fg='red', err=True)
        if "Connection refused" in error_str:
            click.secho("SSH service may not be running on the box.", err=True)
        elif "No route to host" in error_str:
            click.secho("Check your network connection and VPN status.", err=True)
        elif "Permission denied" in error_str:
            click.secho("SSH authentication failed. Check your credentials.", err=True)
        ctx.exit(1)

    click.echo()

    # 4. Display what will be removed and confirm
    if box:
        click.secho(f"Uninstalling lager from {box} ({ip})...", fg='cyan', bold=True)
    else:
        click.secho(f"Uninstalling lager from {ip}...", fg='cyan', bold=True)
    click.echo()
    click.secho("The following will be REMOVED:", fg='yellow', bold=True)
    click.echo("  - Docker containers (lager)")
    if not keep_docker_images:
        click.echo("  - Docker images")
    click.echo("  - ~/box directory")

    if remove_all:
        click.echo("  - /etc/lager directory (saved nets)")
        click.echo("  - Udev rules (/etc/udev/rules.d/lager-*.rules)")
        click.echo("  - Sudoers file (/etc/sudoers.d/lagerdata-udev)")
        click.echo("  - ~/third_party directory")
        click.echo("  - Legacy deploy key (~/.ssh/lager_deploy_key*) if present")
    elif not keep_config:
        click.echo("  - /etc/lager directory (saved nets)")

    click.echo()

    if not yes:
        click.secho("WARNING: This action cannot be undone!", fg='red', bold=True)
        if not click.confirm("Are you sure you want to proceed?", default=False):
            click.echo("Uninstall cancelled.")
            ctx.exit(0)

    click.echo()

    # Helper function to run SSH commands
    def run_ssh(cmd, description, allow_fail=False):
        """Run an SSH command and handle errors."""
        click.echo(f"  {description}...", nl=False)
        try:
            ssh_cmd = ["ssh"]
            if not use_interactive_ssh:
                ssh_cmd.extend(["-o", "BatchMode=yes"])
            ssh_cmd.extend([ssh_host, cmd])

            if use_interactive_ssh:
                # Interactive mode - allow password prompts, don't capture output
                result = subprocess.run(
                    ssh_cmd,
                    timeout=120,
                )
            else:
                # Batch mode - capture output
                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            if result.returncode == 0 or allow_fail:
                click.secho(" done", fg='green')
                return True
            else:
                click.secho(" failed", fg='red')
                # Always show stderr if available for better debugging
                if not use_interactive_ssh and hasattr(result, 'stderr') and result.stderr:
                    stderr_text = result.stderr.strip()
                    click.secho(f"    Error: {stderr_text}", fg='red', err=True)
                    # Provide additional context for common errors
                    if "Permission denied" in stderr_text:
                        click.secho("    Hint: This may require sudo permissions", err=True)
                    elif "No such file" in stderr_text:
                        click.secho("    Hint: File or directory does not exist", err=True)
                elif not use_interactive_ssh and hasattr(result, 'stdout') and result.stdout:
                    # If stderr is empty but stdout has content, it may contain error info
                    stdout_text = result.stdout.strip()
                    if stdout_text:
                        click.secho(f"    Output: {stdout_text}", fg='yellow', err=True)
                return False
        except subprocess.TimeoutExpired:
            click.secho(" timeout", fg='yellow')
            click.secho("    Command timed out. The box may be slow or unresponsive.", err=True)
            return False
        except Exception as e:
            click.secho(f" error: {e}", fg='red')
            return False

    # 5. Stop and remove Docker containers
    click.secho("[Step 1/5] Stopping Docker containers...", fg='cyan')
    run_ssh("docker stop $(docker ps -q) 2>/dev/null || true", "Stopping all containers", allow_fail=True)
    run_ssh("docker rm -f $(docker ps -aq) 2>/dev/null || true", "Removing all containers", allow_fail=True)
    click.echo()

    # 6. Remove Docker images (unless --keep-docker-images)
    click.secho("[Step 2/5] Cleaning Docker...", fg='cyan')
    if not keep_docker_images:
        run_ssh("docker image prune -af 2>/dev/null || true", "Removing Docker images", allow_fail=True)
        run_ssh("docker builder prune -af 2>/dev/null || true", "Clearing Docker build cache", allow_fail=True)
    else:
        click.echo("  Skipping Docker image removal (--keep-docker-images)")
    click.echo()

    # 7. Remove ~/box directory
    click.secho("[Step 3/5] Removing box code...", fg='cyan')
    run_ssh("rm -rf ~/box", "Removing ~/box directory")
    click.echo()

    # 8. Remove /etc/lager (unless --keep-config, or with --all)
    click.secho("[Step 4/5] Removing configuration...", fg='cyan')
    if remove_all or not keep_config:
        run_ssh("sudo rm -rf /etc/lager 2>/dev/null || true", "Removing /etc/lager directory", allow_fail=True)
    else:
        click.echo("  Skipping /etc/lager removal (--keep-config)")
    click.echo()

    # 9. Remove additional components if --all
    click.secho("[Step 5/5] Cleaning up additional components...", fg='cyan')
    if remove_all:
        # Remove udev rules
        run_ssh(
            "sudo rm -f /etc/udev/rules.d/lager-*.rules /etc/udev/rules.d/*lager*.rules 2>/dev/null; "
            "sudo udevadm control --reload-rules 2>/dev/null || true",
            "Removing udev rules",
            allow_fail=True
        )

        # Remove sudoers file
        run_ssh(
            "sudo rm -f /etc/sudoers.d/lagerdata-udev 2>/dev/null || true",
            "Removing sudoers file",
            allow_fail=True
        )

        # Remove third_party directory
        run_ssh("rm -rf ~/third_party", "Removing ~/third_party directory", allow_fail=True)

        # Remove legacy deploy key (from boxes deployed before open-source migration)
        run_ssh(
            "rm -f ~/.ssh/lager_deploy_key ~/.ssh/lager_deploy_key.pub",
            "Removing legacy deploy key",
            allow_fail=True
        )

        # Clean up SSH config (remove legacy GitHub entry for deploy key)
        run_ssh(
            "sed -i '/# Lager deploy key/,/IdentityFile.*lager_deploy_key/d' ~/.ssh/config 2>/dev/null || true",
            "Cleaning SSH config",
            allow_fail=True
        )
    else:
        click.echo("  Skipping additional cleanup (use --all for complete removal)")

    click.echo()
    click.secho("Uninstall complete!", fg='green', bold=True)
    click.echo()
    click.echo(f"The lager box code has been removed from {ip}.")

    if not remove_all and keep_config:
        click.echo()
        click.secho("Note: /etc/lager directory was preserved (contains saved nets).", fg='yellow')

    if not remove_all:
        click.echo()
        click.echo("To completely remove all lager components, run:")
        click.secho(f"  lager uninstall --ip {ip} --all", fg='cyan')