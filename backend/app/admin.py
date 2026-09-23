"""Local operator CLI; no public credit-grant endpoint."""
import argparse
import time
from uuid import uuid4

from .commerce import Commerce


def main():
    parser = argparse.ArgumentParser(description="Castle local accounting tools")
    sub = parser.add_subparsers(dest="command", required=True)
    grant = sub.add_parser("grant", help="Grant funded paid credits to an account")
    grant.add_argument("username")
    grant.add_argument("credits", type=int)
    grant.add_argument("--reason", required=True)
    sub.add_parser("costs", help="Aggregate estimates; no prompts or credentials")
    args = parser.parse_args()
    commerce = Commerce()
    with commerce.transaction() as db:
        if args.command == "grant":
            if args.credits <= 0:
                parser.error("credits must be positive")
            account = db.execute("SELECT id FROM accounts WHERE username=?", (args.username.lower(),)).fetchone()
            if not account:
                parser.error("unknown account")
            db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?)", (uuid4().hex, account[0], "paid", args.credits, args.reason, time.time()))
            print("Granted", args.credits, "credits to", args.username)
        else:
            for row in db.execute("SELECT mode,model,state,COUNT(*) AS attempts,SUM(cost)/1000000.0 AS estimated_usd FROM attempts GROUP BY mode,model,state"):
                print(dict(row))


if __name__ == "__main__":
    main()
