#!/bin/bash
set -e

show_menu() {
    echo "========================================="
    echo "Firewall configuration script"
    echo "========================================="
    echo "Select mode:"
    echo "1) Whitelist mode (all networks) - only whitelisted sites allowed"
    echo "2) Whitelist mode only for SOCKS5 - WireGuard has full access"
    echo "3) Blacklist mode (all networks) - only blacklisted sites blocked"
    echo "4) Blacklist mode only for SOCKS5 - WireGuard has full access"
    echo "5) Reset all rules and restore full access"
    echo "========================================="
    read -p "Enter your choice (1-5): " MODE
}

load_domains() {
    local file=$1
    local ips=()
    
    if [ ! -f "$file" ]; then
        echo "Error: File $file not found" >&2
        return 1
    fi
    
    while IFS= read -r line || [ -n "$line" ]; do
        domain=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        if [[ -z "$domain" || "$domain" =~ ^# ]]; then
            continue
        fi
        
        echo "    Resolving $domain..." >&2
        for dns in "8.8.8.8" "1.1.1.1"; do
            for ip in $(dig +short @$dns "$domain" A 2>/dev/null | grep -E '^[0-9.]+$'); do
                if [[ $ip =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
                    if [[ ! " ${ips[@]} " =~ " $ip " ]]; then
                        ips+=("$ip")
                        echo "      $domain -> $ip" >&2
                    fi
                fi
            done
        done
    done < "$file"
    
    for ip in "${ips[@]}"; do
        echo "$ip"
    done
}

detect_networks() {
    AMN_NET=$(ip route show | grep -E "amn[0-9]+|wg[0-9]+" | awk '{print $1}' | head -1)
    DOCKER_NET=$(ip route show | grep docker0 | awk '{print $1}' | head -1)
    EXT_IF=$(ip route get 8.8.8.8 | awk '{print $5}' | head -1)
    
    if [ -z "$DOCKER_NET" ]; then
        DOCKER_NET="172.17.0.0/16"
    fi
    
    if [ -z "$EXT_IF" ]; then
        echo "Error: Cannot detect external interface"
        exit 1
    fi
    
    echo "Detected networks:"
    echo "  VPN network: ${AMN_NET:-not found}"
    echo "  Docker network: $DOCKER_NET"
    echo "  External interface: $EXT_IF"
}

reset_rules() {
    iptables -P INPUT ACCEPT
    iptables -P FORWARD ACCEPT
    iptables -P OUTPUT ACCEPT
    iptables -F
    iptables -t nat -F
    iptables -t mangle -F
    iptables -X 2>/dev/null || true
    
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    
    iptables -t nat -A POSTROUTING -o $EXT_IF -j MASQUERADE
    iptables -A FORWARD -p udp --dport 53 -j ACCEPT
    iptables -A FORWARD -p tcp --dport 53 -j ACCEPT
    
    echo "All rules have been reset and network access restored"
}

setup_base_rules() {
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    
    iptables -A INPUT -i lo -j ACCEPT
    iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    iptables -A INPUT -p udp --dport $VPN_PORT -j ACCEPT
    iptables -A INPUT -p tcp --dport $SOCKS5_PORT -j ACCEPT
    iptables -A INPUT -p tcp --dport 22 -j ACCEPT
    
    if [ -n "$AMN_NET" ]; then
        iptables -A INPUT -s $AMN_NET -j ACCEPT
    fi
    
    if ip link show docker0 >/dev/null 2>&1; then
        iptables -A INPUT -i docker0 -j ACCEPT
    fi
    
    iptables -P INPUT DROP
    
    iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    iptables -A FORWARD -p udp --dport 53 -j ACCEPT
    iptables -A FORWARD -p tcp --dport 53 -j ACCEPT
}

setup_nat() {
    iptables -t nat -A POSTROUTING -o $EXT_IF -j MASQUERADE
}

allow_all_for_vpn() {
    if [ -n "$AMN_NET" ]; then
        iptables -A FORWARD -s $AMN_NET -j ACCEPT
        iptables -A FORWARD -d $AMN_NET -j ACCEPT
    fi
}

allow_all_for_docker() {
    iptables -A FORWARD -s $DOCKER_NET -j ACCEPT
}

apply_whitelist_for_network() {
    local network=$1
    shift
    local ips=("$@")
    
    if [ ${#ips[@]} -eq 0 ]; then
        echo "    Warning: No IP addresses to whitelist"
        return
    fi
    
    for ip in "${ips[@]}"; do
        if [ -n "$ip" ]; then
            iptables -A FORWARD -s $network -d "$ip" -p tcp -m multiport --dports 80,443 -j ACCEPT
        fi
    done
    
    iptables -A FORWARD -s $network -p tcp --dport 80 -j REJECT --reject-with tcp-reset
    iptables -A FORWARD -s $network -p tcp --dport 443 -j REJECT --reject-with tcp-reset
}

apply_blacklist_for_network() {
    local network=$1
    shift
    local ips=("$@")
    local counter=1
    
    if [ ${#ips[@]} -eq 0 ]; then
        echo "    Warning: No IP addresses to blacklist"
        return
    fi
    
    for ip in "${ips[@]}"; do
        if [ -n "$ip" ]; then
            iptables -I FORWARD $counter -s $network -d "$ip" -p tcp -m multiport --dports 80,443 -j REJECT --reject-with tcp-reset
            counter=$((counter + 1))
        fi
    done
}

finalize_rules() {
    iptables -A FORWARD -j ACCEPT
    iptables -P FORWARD DROP
}

# Main script
SOCKS5_PORT=${1:-33287}
VPN_PORT=${2:-38604}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHITELIST_FILE="$SCRIPT_DIR/whitelist.txt"
BLACKLIST_FILE="$SCRIPT_DIR/blacklist.txt"

detect_networks

show_menu

case $MODE in
    1)
        echo "========================================="
        echo "Mode 1: Whitelist for all networks"
        echo "========================================="
        
        reset_rules
        setup_base_rules
        
        ALL_IPS=()
        while IFS= read -r ip; do
            ALL_IPS+=("$ip")
        done < <(load_domains "$WHITELIST_FILE")
        
        if [ -n "$AMN_NET" ]; then
            apply_whitelist_for_network "$AMN_NET" "${ALL_IPS[@]}"
        fi
        apply_whitelist_for_network "$DOCKER_NET" "${ALL_IPS[@]}"
        
        setup_nat
        finalize_rules
        echo "Whitelist mode enabled for all networks"
        ;;
    
    2)
        echo "========================================="
        echo "Mode 2: Whitelist only for SOCKS5"
        echo "========================================="
        
        reset_rules
        setup_base_rules
        
        allow_all_for_vpn
        
        ALL_IPS=()
        while IFS= read -r ip; do
            ALL_IPS+=("$ip")
        done < <(load_domains "$WHITELIST_FILE")
        
        apply_whitelist_for_network "$DOCKER_NET" "${ALL_IPS[@]}"
        
        setup_nat
        finalize_rules
        echo "Whitelist mode enabled only for SOCKS5"
        echo "WireGuard has full access"
        ;;
    
    3)
        echo "========================================="
        echo "Mode 3: Blacklist for all networks"
        echo "========================================="
        
        reset_rules
        setup_base_rules
        
        allow_all_for_vpn
        allow_all_for_docker
        
        ALL_IPS=()
        while IFS= read -r ip; do
            ALL_IPS+=("$ip")
        done < <(load_domains "$BLACKLIST_FILE")
        
        if [ -n "$AMN_NET" ]; then
            apply_blacklist_for_network "$AMN_NET" "${ALL_IPS[@]}"
        fi
        apply_blacklist_for_network "$DOCKER_NET" "${ALL_IPS[@]}"
        
        setup_nat
        finalize_rules
        echo "Blacklist mode enabled for all networks"
        ;;
    
    4)
        echo "========================================="
        echo "Mode 4: Blacklist only for SOCKS5"
        echo "========================================="
        
        reset_rules
        setup_base_rules
        
        allow_all_for_vpn
        allow_all_for_docker
        
        ALL_IPS=()
        while IFS= read -r ip; do
            ALL_IPS+=("$ip")
        done < <(load_domains "$BLACKLIST_FILE")
        
        apply_blacklist_for_network "$DOCKER_NET" "${ALL_IPS[@]}"
        
        setup_nat
        finalize_rules
        echo "Blacklist mode enabled only for SOCKS5"
        echo "WireGuard has full access"
        ;;
    
    5)
        echo "========================================="
        echo "Mode 5: Reset all rules"
        echo "========================================="
        
        reset_rules
        echo "All rules have been reset and network access restored"
        exit 0
        ;;
    
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo "========================================="
echo "Firewall configured successfully"
echo "To save rules: sudo netfilter-persistent save"
echo "========================================="
