import json
import math
import sys
import pprint

sys.path.append('./perfetto/src/trace_processor/python')

from trace_processor.api import TraceProcessor

from tempfile import NamedTemporaryFile

def load_spec(name):
    with open(name, 'r') as fp:
        return json.load(fp)

def build_query(correlation):
    return ""

def flatten_slices(slices):
    flattened = [slices[0]]
    for slice in slices[1:]:
        if slice['ts'] < flattened[-1]['ts'] + flattened[-1]['dur']:
            flattened[-1]['dur'] = max(slice['ts'] - flattened[-1]['ts'] + slice['dur'], flattened[-1]['dur'])
        else:
            flattened.append(slice)

    return flattened

def get_frame_time_stats(tp, package_name, api):
    # Find the frame interval
    stats = {'histogram': {}, 'busy_histogram': {}}
    sum = 0
    count = 0
    diffs = []
    GPU_SLICE_QUERY = "SELECT ts, dur, submission_id FROM gpu_slice WHERE NOT name='vkQueueSubmit' AND submission_id IS NOT NULL"
    intervals = []
    submission_slices = {}
    if api == "Vulkan":
        # find all vkQueuePresent calls, and all vkQueueSubmit call between them
        interval_query = "SELECT ts FROM slices WHERE name='vkQueuePresentKHR' ORDER BY ts"
        interval_query_it = tp.query(interval_query)
        if len(interval_query_it.cells()) == 0:
            print("Interval query returned no vkQueuePresentKHR slices, trying a fuzzy search")
            interval_query = "SELECT ts FROM slices WHERE name LIKE '%queuepresent%' ORDER BY ts"
            interval_query_it = tp.query(interval_query)
        slices_query_it = tp.query(GPU_SLICE_QUERY)
        for slice_row in slices_query_it:
            if slice_row.submission_id not in submission_slices:
                submission_slices[slice_row.submission_id] = [{'ts': slice_row.ts, 'dur': slice_row.dur}]
            else:
                submission_slices[slice_row.submission_id].append({'ts': slice_row.ts, 'dur': slice_row.dur})
        ts_begin = -1
        ts_end_= -1
        # iterate frame intervals
        for i, interval_row in enumerate(interval_query_it):
            if i == 0:
                ts_end = interval_row.ts
            else:
                frame_slices = []
                ts_begin = ts_end
                ts_end = interval_row.ts
                #SELECT * FROM slices s JOIN track t ON t.id=s.track_id WHERE s.name='vkQueuePresentKHR' ORDER BY ts
                submit_query = "SELECT submission_id FROM gpu_slice WHERE name='vkQueueSubmit' AND ts>={} AND ts<{} ORDER BY ts".format(ts_begin, ts_end)
                submit_query_it = tp.query(submit_query)
                range_max = -math.inf
                range_min = math.inf
                # iterate submissions
                for submit_row in submit_query_it:
                    # iterate slices
                    if submit_row.submission_id in submission_slices:
                        for slice in submission_slices[submit_row.submission_id]:
                            frame_slices.append(slice)
                            range_max = max(range_max, slice['ts'] + slice['dur'])
                            range_min = min(range_min, slice['ts'])
                diff = range_max - range_min
                sum += diff
                count += 1
                flattened = flatten_slices(frame_slices)
                flat_sum = 0
                for slice in flattened:
                    flat_sum += slice['dur']
                key = int(flat_sum / 1000000)
                if key not in stats['busy_histogram']:
                    stats['busy_histogram'][key] = 1
                else:
                    stats['busy_histogram'][key] += 1
                key = int(diff / 1000000)
                if key not in stats['histogram']:
                    stats['histogram'][key] = 1
                else:
                    stats['histogram'][key] += 1
        
    elif api == "GL":
        # this own't work until we have more actionable submission info from vendors
        # interval_query = "SELECT * FROM slices WHERE name LIKE 'eglSwapBuffers'"
        pass
    else:
        raise ValueError("Bad api")

    # Compute the median
    keys = sorted(stats['histogram']) 
    median = 0
    for key in keys:
        median += stats['histogram'][key]
        if median >= count / 2:
            stats['median'] = key
            break

    stats['mean'] = (sum / count) / 1000000
    return stats

def analyze_query(query_result):
    pass

def analyze_trace(tp, spec, package_name, api):
    hists = get_frame_time_stats(tp, package_name, api)
    pprint.pprint(hists)
    # cors = spec['correlations']
    # for cor in cors:
    #     query_str = build_query(cor)
    #     qr_it = tp.query(query_str)
    #     for row in qr_it:
    #         pprint.pprint(dir(row))

if __name__ == '__main__':
    if len(sys.argv) == 5:
        spec = load_spec(sys.argv[2])
        tp = TraceProcessor(file_path=sys.argv[1])
        analyze_trace(tp, spec, sys.argv[3], sys.argv[4])
        # print(spec)
    else:
        print("Incorrect arguments: 'python3 analyze.py trace.perfetto spec/specname.json com.package.name api'")
