import jour.app
import jour.models


def main():
    db = jour.app._get_db()
    settings = jour.models.settings.Settings(db)
    print("openid_client_id:", settings.openid_client_id)
    print("openid_client_secret:", settings.openid_client_secret)
    print("openid_discovery_document:", settings.openid_discovery_document)
    print("scheme:", settings.scheme)


if __name__ == "__main__":
    main()
