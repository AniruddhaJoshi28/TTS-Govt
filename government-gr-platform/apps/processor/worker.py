"""Text-extraction worker; same RQ worker implementation as the downloader."""

from apps.downloader.worker import main

if __name__ == "__main__":
    main()
