import numpy as np
from .surrogate_problem import SurrogateProblem
from .utils import Timer, find_pareto_front, calc_hypervolume
from .factory import init_from_config
from .transformation import StandardTransform
import gc
import scipy, random
'''
Main algorithm framework for Multi-Objective Bayesian Optimization
'''

def computeHV(X, Y, ref_point):
    pfront, pfront_idx = find_pareto_front(Y, return_index=True)
    pset =  X[pfront_idx]
    hv = calc_hypervolume(pfront, ref_point)
    return hv, pfront

#@profile
class MOBO:
    '''
    Base class of algorithm framework, inherit this class with different configs to create new algorithm classes
    '''
    config = {}

    def __init__(self, problem, n_iter, ref_point, framework_args):
        '''
        Input:
            problem: the original / real optimization problem
            n_iter: number of iterations to optimize
            ref_point: reference point for hypervolume calculation
            framework_args: arguments to initialize each component of the framework
        '''
        self.real_problem = problem
        self.n_var, self.n_obj = problem.n_var, problem.n_obj
        self.n_iter = n_iter
        self.ref_point = ref_point
        self.mode = int(framework_args['surrogate']['mode'])
        
#         if self.mode == 2:
#             bounds = np.array([problem.xl, problem.xu])
#             self.transformation = StandardTransform(bounds) # data normalization for surrogate model fitting
#         else:
        self.transformation = None
            
        # framework components
        framework_args['surrogate']['n_var'] = self.n_var # for surrogate fitting
        framework_args['surrogate']['n_obj'] = self.n_obj # for surroagte fitting
        framework_args['solver']['n_obj'] = self.n_obj # for MOEA/D-EGO
        framework = init_from_config(self.config, framework_args)
        
        self.surrogate_model = framework['surrogate'] # surrogate model
        self.acquisition = framework['acquisition'] # acquisition function
        self.solver = framework['solver'] # multi-objective solver for finding the paretofront
        self.selection = framework['selection'] # selection method for choosing new (batch of) samples to evaluate on real problem
        
        # to keep track of data and pareto information (current status of algorithm)
        self.X = None
        self.Y = None
        self.sample_num = 0
        self.status = {
            'pset': None,
            'pfront': None,
            'hv': None,
            'ref_point': self.ref_point,
        }

        # other component-specific information that needs to be stored or exported
        self.info = None

    def _update_status(self, X, Y):
        '''
        Update the status of algorithm from data
        '''
        if self.sample_num == 0:
            self.X = X
            self.Y = Y
        else:
            self.X = np.vstack([self.X, X])
            self.Y = np.vstack([self.Y, Y])
        self.sample_num += len(X)

        self.status['pfront'], pfront_idx = find_pareto_front(self.Y, return_index=True)
        self.status['pset'] = self.X[pfront_idx]
        self.status['hv'] = calc_hypervolume(self.status['pfront'], self.ref_point)

    def solve(self, X_init, Y_init):
        '''
        Solve the real multi-objective problem from initial data (X_init, Y_init)
        '''
        # determine reference point from data if not specified by arguments
        if self.ref_point is None:
            self.ref_point = np.max(Y_init, axis=0)
        self.selection.set_ref_point(self.ref_point)

        self._update_status(X_init, Y_init)

        global_timer = Timer()
        
        
        # solve surrogate problem
#         if self.mode == 1 or self.mode == 0:
        bound = [self.real_problem.xl, self.real_problem.xu]
#         else:
#             bound = None
        last_hv = 0
        for i in range(self.n_iter):
            print('========== Iteration %d ==========' % i)

            timer = Timer()

            # data normalization
            X, Y = self.X, self.Y
            # build surrogate models
            self.surrogate_model.fit(X, Y, bound, self.mode)
            
            timer.log('Surrogate model fitted')

            # define acquisition functions
            self.acquisition.fit(X, Y)
            surr_problem = SurrogateProblem(self.real_problem, self.surrogate_model, self.acquisition, self.transformation)
            
            solution = self.solver.solve(surr_problem, X, Y, self.mode, bound)
            timer.log('Surrogate problem solved')
            # batch point selection
            self.selection.fit(X, Y)
            X_next, self.info = self.selection.select(solution, surr_problem.surrogate_model, self.status, self.transformation)
            timer.log('Next sample batch selected')
            if self.mode == 0:
                X_next = np.round(X_next)
                
            timer.log('New samples evaluated')
            Y_next = self.real_problem.evaluate(X_next, return_values_of="F")
            if self.mode == 2:
                hv, old_pfront = computeHV(np.vstack([self.X, X_next]), np.vstack([self.Y, Y_next]), self.ref_point)
                print("current: " + str(hv) + " - last: " + str(last_hv))
                if hv == last_hv:
                    distance = scipy.spatial.distance.directed_hausdorff(old_pfront, last_pfront.reshape(-1,2))[0]
                    surr_problem.acquisition.setFactor(0.1)
                    solution = self.solver.solve(surr_problem, X, Y, self.mode, bound)
                    self.selection.fit(X, Y)
                    x_new, _ = self.selection.select(solution, surr_problem.surrogate_model, self.status, self.transformation)
                    y_new = self.real_problem.evaluate(x_new, return_values_of="F")
                    new_hv, pfront = computeHV(np.vstack([self.X, x_new]), np.vstack([self.Y, y_new]), self.ref_point)
                    print(distance)
                    surr_problem.acquisition.setFactor(None)
                    if distance < 0.02:
                        old_factor = surr_problem.acquisition.getFactor()
                        x_new, y_new = [], []
                        #############################
                        #### Use optimizer to find value of factor
                        #############################
                        def function(factor):
                            surr_problem.acquisition.setFactor(factor)
                            #surr_problem.surrogate_model.setLength(l)
                            solution = self.solver.solve(surr_problem, X, Y, self.mode, bound, 20)
                            self.selection.fit(X, Y)
                            
                            x_new, _ = self.selection.select(solution, surr_problem.surrogate_model, self.status, self.transformation)
                            y_new = self.real_problem.evaluate(x_new, return_values_of="F")
                            new_hv, pfront = computeHV(np.vstack([self.X, x_new]), np.vstack([self.Y, y_new]), self.ref_point)
                            new_distance = scipy.spatial.distance.directed_hausdorff(old_pfront, pfront)[0]
                            P = 0
                            if new_distance < 0.0005:
                                P = 1
                            delta_hv = new_hv - last_hv
                            result = P - delta_hv + factor - old_factor # new_distance # (factor - old_factor)  # P
                            print(str(factor) + " : " + str(result) + " : " + str(new_distance) + " : " + str(delta_hv))
                            return result
                        def re_compute_function(factor):
                            surr_problem.acquisition.setFactor(factor)
                            #surr_problem.surrogate_model.setLength(l)
                            solution = self.solver.solve(surr_problem, X, Y, self.mode, bound)
                            self.selection.fit(X, Y)
                            
                            x_new, _ = self.selection.select(solution, self.surrogate_model, self.status, self.transformation)
                            y_new = self.real_problem.evaluate(x_new, return_values_of="F")
                            return x_new, y_new
                        initFactor = [random.random()] # [0]
                        x0 = np.array(initFactor) #  + initL
                        bounds = [(0, 1)]
                        print(initFactor)
                        res = scipy.optimize.minimize(function, x0, bounds=bounds, method='L-BFGS-B', options={'maxiter': 2})
                        print("chose: " + str(res['x']))
                        print(res)
                        x_new, y_new = re_compute_function (res['x'])
                        timer.log('Adjust the factor')
                        if len(x_new) > 0:
                            self._update_status(x_new, y_new)
                        else:
                            self._update_status(X_next, Y_next)
                        surr_problem.acquisition.setFactor(None)
                    else:
                        self._update_status(X_next, Y_next)
                else:
                    self._update_status(X_next, Y_next)
            else:
                self._update_status(X_next, Y_next)
                
            last_hv = self.status['hv']
            last_pfront = self.status['pfront'].reshape(2, -1)
            global_timer.log('Total runtime', reset=False)
            print('Total evaluations: %d, hypervolume: %.4f\n' % (self.sample_num, self.status['hv']))
            
            del X, Y, surr_problem, solution
            # return new data iteration by iteration
            gc.collect()
            yield X_next, Y_next, self.status['pfront']

    def __str__(self):
        return \
            '========== Framework Description ==========\n' + \
            f'# algorithm: {self.__class__.__name__}\n' + \
            f'# surrogate: {self.surrogate_model.__class__.__name__}\n' + \
            f'# acquisition: {self.acquisition.__class__.__name__}\n' + \
            f'# solver: {self.solver.__class__.__name__}\n' + \
            f'# selection: {self.selection.__class__.__name__}\n'
