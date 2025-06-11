import tkinter as tk
from tkinter import messagebox, simpledialog
from web3 import Web3
import mysql.connector
from datetime import datetime

# === Web3 Setup ===
web3 = Web3(Web3.HTTPProvider("http://127.0.0.1:7545"))
ganache_accounts = web3.eth.accounts

# === Globals for Pending Transactions ===
pending_transactions = 0
pending_tx_hashes = []

# === Database Connection ===
def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='Siri@0071',
        database='eth_simulator'
    )

# === Helper Functions ===
def get_account_by_name(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT account_name, address, private_key FROM accounts WHERE account_name = %s", (name,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return {'name': result[0], 'address': result[1], 'private_key': result[2]} if result else None

def get_account_name_by_address(address):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT account_name FROM accounts WHERE address = %s", (address,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else None

def check_if_account_exists(address_or_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM accounts WHERE address = %s OR account_name = %s", (address_or_name, address_or_name))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return bool(result)

def update_balance(address, delta_eth):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE accounts SET balance_eth = balance_eth + %s WHERE address = %s", (delta_eth, address))
    conn.commit()
    cursor.close()
    conn.close()

def store_transaction(data):
    sender_name = get_account_name_by_address(data['sender'])
    receiver_name = get_account_name_by_address(data['receiver'])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transactions (tx_hash, sender, receiver, value_eth, gas_used, block_number, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        data['tx_hash'], sender_name, receiver_name,
        data['value_eth'], data['gas_used'], data['block_number'], datetime.now()
    ))
    conn.commit()
    cursor.close()
    conn.close()

# === Main Functionalities ===
def create_account():
    account_name = simpledialog.askstring("New Account", "Enter account name:")
    if not account_name:
        return

    if check_if_account_exists(account_name):
        messagebox.showerror("Error", f"Account '{account_name}' already exists.")
        return

    account = web3.eth.account.create()
    address, private_key, balance = account.address, account.key.hex(), 50.0

    funder = next((acc for acc in ganache_accounts if web3.from_wei(web3.eth.get_balance(acc), 'ether') > balance), None)
    if not funder:
        messagebox.showerror("Error", "No Ganache account has enough balance.")
        return

    try:
        tx = {
            'from': funder, 'to': address, 'value': web3.to_wei(balance, 'ether'),
            'gas': 21000, 'gasPrice': web3.to_wei('50', 'gwei'),
            'nonce': web3.eth.get_transaction_count(funder)
        }
        tx_hash = web3.eth.send_transaction(tx)
        web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    except Exception as e:
        messagebox.showerror("Funding Error", str(e))
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO accounts (account_name, private_key, address, balance_eth) VALUES (%s, %s, %s, %s)",
                   (account_name, private_key, address, balance))
    conn.commit()
    cursor.close()
    conn.close()

    messagebox.showinfo("Success", f"Account '{account_name}' created and funded.")

def send_eth():
    global pending_transactions, pending_tx_hashes

    sender_name = simpledialog.askstring("Send ETH", "Sender name:")
    receiver_name = simpledialog.askstring("Send ETH", "Receiver name:")
    try:
        amount = float(simpledialog.askstring("Send ETH", "Amount in ETH:"))
    except:
        messagebox.showerror("Error", "Invalid amount.")
        return

    sender = get_account_by_name(sender_name)
    receiver = get_account_by_name(receiver_name)
    if not sender or not receiver:
        messagebox.showerror("Error", "Sender or receiver not found.")
        return

    try:
        nonce = web3.eth.get_transaction_count(sender['address'], 'pending')

        tx = {
            'nonce': nonce,
            'to': receiver['address'],
            'value': web3.to_wei(amount, 'ether'),
            'gas': 21000,
            'gasPrice': web3.to_wei('50', 'gwei')
        }

        signed = web3.eth.account.sign_transaction(tx, sender['private_key'])
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)

        pending_transactions += 1
        pending_tx_hashes.append((tx_hash.hex(), sender, receiver, amount))

        if pending_transactions >= 5:
            web3.provider.make_request('evm_mine', [])
            block_number = web3.eth.block_number

            for tx_data in pending_tx_hashes:
                tx_hash, sender_data, receiver_data, amount_value = tx_data
                receipt = web3.eth.get_transaction_receipt(tx_hash)
                tx_data_store = {
                    'tx_hash': tx_hash,
                    'sender': sender_data['address'],
                    'receiver': receiver_data['address'],
                    'value_eth': amount_value,
                    'gas_used': receipt.gasUsed,
                    'block_number': block_number
                }
                store_transaction(tx_data_store)
                update_balance(sender_data['address'], -amount_value)
                update_balance(receiver_data['address'], amount_value)

            pending_transactions = 0
            pending_tx_hashes = []
            messagebox.showinfo("Mined", f"Block #{block_number} mined with 5 transactions.")

        else:
            messagebox.showinfo("Queued", f"Transaction queued. Pending {pending_transactions}/5")

    except Exception as e:
        messagebox.showerror("Transaction Error", str(e))

def view_accounts():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT account_name, balance_eth FROM accounts")
    accounts = cursor.fetchall()
    cursor.close()
    conn.close()

    info = "\n".join(f"{name}: {balance:.4f} ETH" for name, balance in accounts)
    messagebox.showinfo("Accounts", info or "No accounts available.")

def delete_account():
    name = simpledialog.askstring("Delete Account", "Enter account name to delete:")
    if not name:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM accounts WHERE account_name = %s", (name,))
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()

    messagebox.showinfo("Delete", "Deleted." if affected else "Account not found.")

def view_transactions():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sender, receiver, value_eth, gas_used, block_number, timestamp FROM transactions ORDER BY timestamp DESC
    """)
    transactions = cursor.fetchall()
    cursor.close()
    conn.close()

    info = ""
    for tx in transactions:
        sender = tx[0] if check_if_account_exists(tx[0]) else f"[{tx[0]}]"
        receiver = tx[1] if check_if_account_exists(tx[1]) else f"[{tx[1]}]"
        info += (f"From: {sender} ➡ To: {receiver}\n"
                 f"Amount: {tx[2]} ETH | Gas: {tx[3]} | Block: {tx[4]} | Time: {tx[5]}\n" + "-" * 50 + "\n")
    messagebox.showinfo("Transactions", info or "No transactions.")

def search_transactions():
    name = simpledialog.askstring("Search", "Enter account name:")
    if not name:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sender, receiver, value_eth, gas_used, block_number, timestamp FROM transactions 
        WHERE sender = %s OR receiver = %s ORDER BY timestamp DESC
    """, (name, name))
    transactions = cursor.fetchall()
    cursor.close()
    conn.close()

    info = ""
    for tx in transactions:
        sender = tx[0] if check_if_account_exists(tx[0]) else f"[{tx[0]}]"
        receiver = tx[1] if check_if_account_exists(tx[1]) else f"[{tx[1]}]"
        info += (f"From: {sender} ➡ To: {receiver}\n"
                 f"Amount: {tx[2]} ETH | Gas: {tx[3]} | Block: {tx[4]} | Time: {tx[5]}\n" + "-" * 50 + "\n")
    messagebox.showinfo("Search Results", info or "No transactions.")

def view_blockchain():
    try:
        latest_block = web3.eth.block_number
        info = ""

        for block_number in range(0, latest_block + 1):
            block = web3.eth.get_block(block_number)
            info += (f"Block Number: {block.number}\n"
                     f"Hash: {block.hash.hex()}\n"
                     f"Previous Hash: {block.parentHash.hex()}\n"
                     f"Timestamp: {datetime.fromtimestamp(block.timestamp)}\n"
                     f"Transactions: {len(block.transactions)}\n"
                     + "-" * 50 + "\n")

        if info:
            messagebox.showinfo("Blockchain", info)
        else:
            messagebox.showinfo("Blockchain", "No blocks found.")

    except Exception as e:
        messagebox.showerror("Blockchain Error", str(e))

# === GUI App ===
app = tk.Tk()
app.title("Ethereum Wallet Simulator")  
app.geometry("400x550")

tk.Label(app, text="Ethereum Wallet Simulator", font=("Helvetica", 16, "bold")).pack(pady=10)
tk.Button(app, text="Create Account", command=create_account, width=30).pack(pady=5)
tk.Button(app, text="Send ETH", command=send_eth, width=30).pack(pady=5)
tk.Button(app, text="View Accounts", command=view_accounts, width=30).pack(pady=5)
tk.Button(app, text="View Transactions", command=view_transactions, width=30).pack(pady=5)
tk.Button(app, text="Search Transactions", command=search_transactions, width=30).pack(pady=5)
tk.Button(app, text="View Blockchain", command=view_blockchain, width=30).pack(pady=5)
tk.Button(app, text="Delete Account", command=delete_account, width=30).pack(pady=5)
tk.Button(app, text="Exit", command=app.quit, width=30).pack(pady=20)

app.mainloop()
