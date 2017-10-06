import requests


def get_peers(tracker_url, info_hash, peer_id, port, uploaded=0, downloaded=0, left=0, event='started'):
    info_hash = requests.utils.quote(info_hash)

    data = {'info_hash': info_hash,
            'peer_id': peer_id,
            'port': port,
            'uploaded': uploaded,
            'downloaded': downloaded,
            'left': left,
            'event': event,
            'numwant': 100,
            'no_peer_id': 1}
    response = requests.get(url=tracker_url, data=data)
    print response