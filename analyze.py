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
    stats = {'busy_sum_frametimes': {}, 'busy_span_frametimes': {}}
    QUEUE_QUERY = "SELECT s.name, s.ts, s.dur, g.submission_id FROM slices s \
        LEFT JOIN gpu_slice g ON g.name=s.name AND s.ts=g.ts AND s.dur=g.dur \
        WHERE s.name='vkQueuePresentKHR' or (g.submission_id IS NOT NULL and g.name='vkQueueSubmit') \
        ORDER BY s.ts"
    GPU_SLICE_QUERY = "SELECT * FROM gpu_slice WHERE name!='vkQueueSubmit' and submission_id IS NOT NULL ORDER BY ts"
    busy_sum = 0
    busy_span_sum = 0
    count = 0
    intervals = []
    submission_slices = {}
    submit_slices = []
    if api == "Vulkan":
        # do a rather cumbersome enumeration to avoid slamming the database
        slices_query_it = tp.query(GPU_SLICE_QUERY)
        for slice_row in slices_query_it:
            if slice_row.submission_id not in submission_slices:
                submission_slices[slice_row.submission_id] = [{'ts': slice_row.ts, 'dur': slice_row.dur}]
            else:
                submission_slices[slice_row.submission_id].append({'ts': slice_row.ts, 'dur': slice_row.dur})
        # find all vkQueuePresent calls, and all vkQueueSubmit call between them
        # iterate frame intervals
        queue_query_it = tp.query(QUEUE_QUERY)
        for queue_row in queue_query_it:
            print(queue_row.name)
            if queue_row.name == 'vkQueuePresentKHR':
                intervals.append([])
            if len(intervals) > 0 and queue_row.submission_id in submission_slices and queue_row.name != 'vkQueuePresentKHR':
                intervals[-1] += submission_slices[queue_row.submission_id]

        for interval in intervals:
            if len(interval) > 0:
                count += 1
                flattened_slices = flatten_slices(interval)
                active_time = sum(map(lambda s: s['dur'], flattened_slices))
                range_max = -math.inf
                range_min = math.inf
                # iterate submissions
                for gpu_slice in interval:
                    range_max = max(range_max, gpu_slice['ts'] + gpu_slice['dur'])
                    range_min = min(range_min, gpu_slice['ts'])
                span_time = range_max - range_min
                key = int(active_time / 1000000)
                if key not in stats['busy_sum_frametimes']:
                    stats['busy_sum_frametimes'][key] = 1
                else:
                    stats['busy_sum_frametimes'][key] += 1
                key = int(span_time / 1000000)
                if key not in stats['busy_span_frametimes']:
                    stats['busy_span_frametimes'][key] = 1
                else:
                    stats['busy_span_frametimes'][key] += 1

    elif api == "GL":
        # this own't work until we have more actionable submission info from vendors
        # interval_query = "SELECT * FROM slices WHERE name LIKE 'eglSwapBuffers'"
        pass
    else:
        raise ValueError("Bad api")

    # Compute the median
    keys = sorted(stats['busy_sum_frametimes']) 
    median = 0
    for key in keys:
        median += stats['busy_sum_frametimes'][key]
        if median >= count / 2:
            stats['busy_sum_median'] = key
            break

    keys = sorted(stats['busy_span_frametimes']) 
    median = 0
    for key in keys:
        median += stats['busy_span_frametimes'][key]
        if median >= count / 2:
            stats['busy_span_median'] = key
            break

    # stats['mean'] = (sum / count) / 1000000
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
