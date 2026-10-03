"""Manual allocation probe; run with conda run -n agent python tests/figura_execution_payload_memory_probe.py.

Figures exclude input objects allocated before tracemalloc starts. They measure
incremental Python allocations, not process RSS or a production memory ceiling.
"""

import tracemalloc
from figura.shared.payloads import encode_json, decode_json
N = 32 * 1024 * 1024 - 8192
for label, value in (
    ('request', {'messages':[{'role':'user','content':'x'*N}]}),
    ('registry', {'tools':[{'name':'t','description':'x'*N,'parameters':{'type':'object'},'result_schema':{'type':'object'}}]}),
    ('response', {'assistant_content':'x'*N,'tool_calls':[],'continuation':None}),
    ('continuation', {'reasoning_content':'x'*N,'provider_id':'qwen','format_version':1}),
):
    tracemalloc.start()
    encoded=encode_json(value)
    peak=tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    tracemalloc.start()
    decoded=decode_json(encoded)
    receive_peak=tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    print(label, 'encoded_bytes', len(encoded.encode()), 'encode_peak_mib', round(peak/2**20, 2), 'decode_peak_mib', round(receive_peak/2**20, 2))
    del encoded, decoded
from figura.providers.transport import _BoundedStream
from figura.providers.errors import ProviderProtocolError
import httpx
class RawStream(httpx.SyncByteStream):
    def __iter__(self):
        for _ in range(512):
            yield b'x' * 65536
stream = _BoundedStream(RawStream(), 32 * 1024 * 1024)
tracemalloc.start()
received = b''.join(stream)
print('bounded_receive', 'bytes', len(received), 'peak_mib', round(tracemalloc.get_traced_memory()[1]/2**20, 2))
tracemalloc.stop()
del received
stream = _BoundedStream(RawStream(), 32 * 1024 * 1024 - 1)
try:
    b''.join(stream)
except ProviderProtocolError:
    print('oversize_receive', 'rejected_before_parse', True)
class JsonBody(httpx.SyncByteStream):
    def __iter__(self):
        yield b'{"choices":[{"message":{"content":"'
        for _ in range(511):
            yield b'x' * 65536
        yield b'"}}]}'
tracemalloc.start()
result = decode_json(b''.join(_BoundedStream(JsonBody(), 32 * 1024 * 1024)).decode('utf-8'))
print('receive_decode_combined', 'content_bytes', len(result['choices'][0]['message']['content']), 'peak_mib', round(tracemalloc.get_traced_memory()[1]/2**20, 2))
tracemalloc.stop()
