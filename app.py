import os
import time
import string

import redis
from flask import request, Flask, jsonify

app = Flask(__name__)
r = redis.Redis()

hex_digits = set(string.hexdigits.lower())
validate_hash = lambda hash: len(hash) % 16 == 0 and len(hash) <= 128 and all(chr in hex_digits for chr in hash)

byte_seconds = 86400 * 365 * 2 #16 Byte Years
max_value_size = 16 * 1024 #16 KB
max_get_hashes = 64
max_post_size = 1024 * 1024 * 1024 #1 MB

@app.route('/', methods=['GET', 'POST'])
def index():
	minute = str(int(time.time()) / 60)
	ip_address = ''
	with r.pipeline() as pipe:
		pipe.incr('ratelimit.'+ip_address+'.'+minute)
		pipe.expire('ratelimit.'+ip_address+'.'+minute, 60)
		hits, _ = pipe.execute()
	if hits > 180:
		return 'Rate limit for this minute reached, slow down cowboy'
	if request.method == 'POST':
		insert_time = int(time.time())
		current_post_size = 0
		with r.pipeline() as pipe:
			for hash, values in request.form.lists():
				if validate_hash(hash):
					longest_expire_time = 0
					for i, v in enumerate(values):
						if len(v) < max_value_size and current_post_size < max_post_size:
							hash_key = '{hash}-{insert_time}-{i}'.format(hash=hash, insert_time=insert_time, i=i)
							expire_time = byte_seconds / len(v)
							if expire_time > longest_expire_time:
								longest_expire_time = expire_time
							pipe.set(hash_key, v)
							pipe.expire(hash_key, expire_time)
							pipe.sadd('list.'+hash, hash_key)
							current_post_size += len(v)
					pipe.expire('list.'+hash, longest_expire_time)
			pipe.execute()
		return 'ok'
	else:
		hashes = [hash for hash in request.args.getlist('hash') if validate_hash(hash)][:max_get_hashes]
		hash_list_keys = ['list.'+hash for hash in hashes]
		with r.pipeline() as pipe:
			for hash_list_key in hash_list_keys:
				pipe.smembers(hash_list_key)
			hash_lists = pipe.execute()
		with r.pipeline() as pipe:
			for hash_list in hash_lists:
				pipe.mget(hash_list)
			hash_list_values = pipe.execute()

		expired_hash_keys = []
		data = {}
		with r.pipeline() as pipe:
			for keys, values in zip(hash_lists, hash_list_values):
				for k, v in zip(keys, values):
					hash = k.split('-')[0]
					if v != None:
						insert_time = int(k.split('-')[1])
						if hash not in data:
							data[hash] = {}
						if insert_time not in data[hash]:
							data[hash][insert_time] = []
						data[hash][insert_time].append(v)
					else:
						pipe.srem('list.'+hash, k)
			pipe.execute()
		return jsonify(**data)

if __name__ == '__main__':
	port = int(os.environ.get('PORT', 5000))
	app.run(host='0.0.0.0', port=port)